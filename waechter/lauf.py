"""Ein vollständiger Prüflauf über alle konfigurierten Händler."""

from __future__ import annotations

import datetime as dt
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from . import modelle as m
from . import ereignisse as ev
from . import fakecheck
from . import telegram
from .haendler import shopify
from .klassifizierung import klassifiziere
from .konfig import Konfig, Shop, ist_ausgeschlossen
from .speicher import Speicher
from .status import bestimme_status
from .zuordnung import ordne_zu


def _titeltext(titel: str, variante: str) -> str:
    return titel if (variante or "").lower() in ("", "default title") else f"{titel} {variante}"


def _versand_hinweis(shop: Shop, versand: Optional[int], waehrung: Optional[str]) -> str:
    if shop.versand_de.status != "bekannt":
        return "Versandkosten nach DE unbekannt"
    if waehrung != "EUR":
        return "Versand nicht berechenbar (Preiswährung nicht EUR bestätigt)"
    if versand is None:
        return "Versandkosten nicht berechenbar"
    return f"laut Versandseite ({shop.versand_de.geprueft_am})"


def jetzt_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _beobachtenswert(eintrag: dict, jetzt: dt.datetime) -> bool:
    """Schnelle Runde: Angebote, die gerade nicht lieferbar sind, in JEDEM Lauf; lieferbare nur alle ~10 Minuten
    (dort geht es nur um Preisrückgänge und das Erkennen von Ausverkauf)."""
    letzte = eintrag.get("letzte") or {}
    if letzte.get("status") != m.IN_STOCK:
        return True
    alter = _alter_min(eintrag.get("zuletzt_geprueft"), jetzt)
    return alter is None or alter >= 10


def baue_beobachtung(shop: Shop, js: dict, v: dict, k: m.Klassifizierung, t: m.Treffer, info: dict,
                     zeitpunkt: str, heute: dt.date) -> m.Beobachtung:
    preis = shopify.preis_cent_aus_js(v)
    waehrungen = info.get("waehrungen", [])
    if waehrungen == [shop.waehrung]:
        waehrung, bestaetigt = shop.waehrung, True
    elif not waehrungen:
        waehrung, bestaetigt = shop.waehrung, bool(shop.pruefung.get("waehrung_aus_pruefung"))
    else:
        waehrung, bestaetigt = (waehrungen[0] if len(waehrungen) == 1 else None), False
    status, gruende = bestimme_status(
        verfuegbar=v.get("available") if isinstance(v.get("available"), bool) else None,
        bestand_verfolgt=shopify.bestand_verfolgt(v), titel=js.get("title", ""), variante=v.get("title", ""),
        tags=js.get("tags", []) or [], beschreibung=js.get("description", "") or "",
        verkaufsplaene=shopify.verkaufsplaene(js),
        schema_verfuegbarkeit=shopify.schema_verfuegbarkeit(info, v.get("id")), heute=heute)
    if not waehrungen:
        gruende.append("Währung laut Händlerprüfung (nicht auf der Seite sichtbar)" if bestaetigt
                       else "Währung nicht auf der Seite bestätigt (Konfigurationswert verwendet)")
    elif not bestaetigt:
        gruende.append(f"Seite zeigt Währung {', '.join(waehrungen)} statt {shop.waehrung}")
    if info.get("seitenfehler"):
        gruende.append(f"sichtbare Produktseite: {info['seitenfehler']}")
    if preis is None and status in m.KAUFBAR:
        status = m.UNCLEAR
        gruende.append("Preis fehlt oder 0,00 (Platzhalter) – Status unklar")
    versand = shop.versand_de.kosten_cent(preis) if waehrung == "EUR" else None
    gesamt = preis + versand if (preis is not None and versand is not None) else None
    mehrere = len(js.get("variants", [])) > 1
    url = shopify.produkt_url(shop.basis_url, js.get("handle", "")) + (f"?variant={v.get('id')}" if mehrere else "")
    return m.Beobachtung(
        angebot_id=f"{shop.id}:{js.get('handle')}:{v.get('id')}", shop_id=shop.id, shop_name=shop.name,
        ziel_id=t.ziel_id, ziel_anzeige=t.anzeige, kategorie=t.kategorie, sicherheit=t.sicherheit,
        prioritaet=t.prioritaet, titel=js.get("title", ""),
        variante="" if (v.get("title") or "").lower() == "default title" else (v.get("title") or ""),
        url=url, zeitpunkt=zeitpunkt, abruf_ok=True, status=status, status_gruende=gruende,
        sprache=k.sprache, typ=k.typ, set_code=k.set_code, versiegelt=k.versiegelt, vollstaendig=k.vollstaendig,
        preis_cent=preis, waehrung=waehrung, waehrung_bestaetigt=bestaetigt, versand_cent=versand,
        versand_hinweis=_versand_hinweis(shop, versand, waehrung), gesamt_cent=gesamt,
        treffer_gruende=t.gruende)


def fehler_beobachtung(shop: Shop, angebot_id: str, vorlage: dict, url: str, fehler: str,
                       zeitpunkt: str) -> m.Beobachtung:
    """Abruffehler: wird gespeichert, löst aber nie ein Ereignis aus (Status UNCLEAR)."""
    return m.Beobachtung(
        angebot_id=angebot_id, shop_id=shop.id, shop_name=shop.name,
        ziel_id=vorlage.get("ziel_id", "?"), ziel_anzeige=vorlage.get("ziel_anzeige", "?"),
        kategorie=vorlage.get("kategorie", "?"), sicherheit=vorlage.get("sicherheit", m.UNSICHER),
        prioritaet=vorlage.get("prioritaet", False), titel=vorlage.get("titel", ""),
        variante=vorlage.get("variante", ""), url=url, zeitpunkt=zeitpunkt, abruf_ok=False, status=m.UNCLEAR,
        status_gruende=["Abruffehler – kein Statuswechsel abgeleitet"], sprache=vorlage.get("sprache", m.UNBEKANNT),
        typ=vorlage.get("typ", m.TYP_UNBEKANNT), set_code=vorlage.get("set_code"),
        versiegelt=vorlage.get("versiegelt", m.UNBEKANNT), vollstaendig=vorlage.get("vollstaendig", m.UNBEKANNT),
        preis_cent=None, waehrung=None, waehrung_bestaetigt=False, versand_cent=None,
        versand_hinweis="unbekannt (Abruffehler)", gesamt_cent=None, fehler=fehler)


def pruefe_shop(shop: Shop, konfig: Konfig, abrufer, zustand: dict, zeitpunkt: str, heute: dt.date,
                log: Callable[[str], None], modus: str = "voll") -> tuple[list[m.Beobachtung], list[dict], dict]:
    if shop.plattform != "shopify":   # WooCommerce, Shopware, JTL, … (HTML-Auswertung)
        from .onepiece_generisch import pruefe_shop_generisch
        return pruefe_shop_generisch(shop, konfig, abrufer, zustand, zeitpunkt, heute, log, modus)
    setnamen = konfig.produkte.get("displays", {}).get("setnamen", {})
    bericht = {"name": shop.name, "listen_ok": False, "fehler": [], "produkte_gelesen": 0,
               "kandidaten": 0, "seiten_geprueft": 0, "modus": modus}
    beobachtungen: list[m.Beobachtung] = []
    ausgeschlossen: list[dict] = []

    pause = abrufer.host_pausiert(shop.host)
    if pause:
        bericht["fehler"].append(f"Shop übersprungen: {pause}")
        return beobachtungen, ausgeschlossen, bericht

    if modus == "schnell":   # nur bekannte Angebote prüfen – kein Katalog-Scan
        produkte, fehler, liste_ok = [], [], True
    else:
        produkte, fehler, liste_ok = shopify.liste_produkte(shop, abrufer)
    bericht.update(listen_ok=liste_ok, produkte_gelesen=len(produkte))
    bericht["fehler"].extend(fehler)

    # 1) Kandidaten aus der Produktliste (nur zum Finden – kein Verfügbarkeitsnachweis)
    zu_pruefen: dict[str, dict[str, dict]] = {}
    for p in produkte:
        for v in p.get("variants", []) or []:
            tt = _titeltext(p.get("title", ""), v.get("title", ""))
            k = klassifiziere(p.get("title", ""), v.get("title", ""), p.get("handle", ""), p.get("tags", []),
                              p.get("body_html", "") or "", p.get("vendor", ""), p.get("product_type", ""), setnamen)
            t, grund = ordne_zu(tt, k, konfig.produkte)
            if t is None:
                if k.ist_one_piece:
                    ausgeschlossen.append({"shop": shop.name, "titel": tt, "grund": grund,
                                           "url": shopify.produkt_url(shop.basis_url, p.get("handle", ""))})
                continue
            zu_pruefen.setdefault(p["handle"], {})[str(v.get("id"))] = {
                "titel": p.get("title", ""), "variante": v.get("title", ""), "ziel_id": t.ziel_id,
                "ziel_anzeige": t.anzeige, "kategorie": t.kategorie, "sicherheit": t.sicherheit,
                "prioritaet": t.prioritaet, "sprache": k.sprache, "typ": k.typ, "set_code": k.set_code,
                "versiegelt": k.versiegelt, "vollstaendig": k.vollstaendig}

    # 1b) Große Shops: Katalog wird nach max_seiten abgeschnitten – One-Piece-Displays dahinter über die Shop-Suche finden
    if modus == "voll" and liste_ok and len(produkte) >= shop.max_seiten * 250:
        for p in shopify.suche_vorschlaege(shop, abrufer):
            tt = p.get("title", "")
            k = klassifiziere(tt, "", p.get("handle", ""), [], "", p.get("vendor", ""), p.get("type", ""), setnamen)
            t, grund = ordne_zu(tt, k, konfig.produkte)
            if t is not None and p.get("handle"):
                zu_pruefen.setdefault(p["handle"], {})

    # 2) Bereits bekannte Angebote, die nicht mehr in der Liste stehen, trotzdem direkt prüfen
    for aid, eintrag in zustand["angebote"].items():
        if not aid.startswith(shop.id + ":"):
            continue
        if modus == "schnell" and not _beobachtenswert(eintrag, jetzt_utc()):
            continue
        _, handle, vid = aid.split(":", 2)
        if handle not in zu_pruefen or vid not in zu_pruefen[handle]:
            zu_pruefen.setdefault(handle, {})[vid] = dict(eintrag.get("letzte") or {})
    bericht["kandidaten"] = sum(len(x) for x in zu_pruefen.values())

    # 3) Konkrete Produktseiten abrufen
    for handle, varianten in sorted(zu_pruefen.items()):
        js, info, fehler = shopify.hole_produkt(shop, handle, abrufer)
        url = shopify.produkt_url(shop.basis_url, handle)
        if js is None:
            for vid, vorlage in varianten.items():
                beobachtungen.append(fehler_beobachtung(shop, f"{shop.id}:{handle}:{vid}", vorlage, url,
                                                        "; ".join(fehler) or "unbekannter Fehler", zeitpunkt))
            continue
        bericht["seiten_geprueft"] += 1
        gesehen = set()
        for v in js.get("variants", []) or []:
            vid = str(v.get("id"))
            tt = _titeltext(js.get("title", ""), v.get("title", ""))
            k = klassifiziere(js.get("title", ""), v.get("title", ""), js.get("handle", handle), js.get("tags", []),
                              js.get("description", "") or "", js.get("vendor", ""), js.get("type", ""), setnamen)
            t, grund = ordne_zu(tt, k, konfig.produkte)
            if t is None:
                if vid in varianten:
                    ausgeschlossen.append({"shop": shop.name, "titel": tt, "grund": f"Produktseite: {grund}", "url": url})
                continue
            gesehen.add(vid)
            beobachtungen.append(baue_beobachtung(shop, js, v, k, t, info, zeitpunkt, heute))
        for vid, vorlage in varianten.items():
            if vid not in gesehen and vid not in {str(v.get("id")) for v in js.get("variants", [])}:
                beobachtungen.append(fehler_beobachtung(shop, f"{shop.id}:{handle}:{vid}", vorlage, url,
                                                        "Variante auf der Produktseite nicht mehr vorhanden", zeitpunkt))
    log(f"  {shop.name}: {len(produkte)} Produkte gelesen, {bericht['kandidaten']} Kandidaten, "
        f"{bericht['seiten_geprueft']} Produktseiten geprüft, {len(bericht['fehler'])} Listenfehler")
    return beobachtungen, ausgeschlossen, bericht


def _alter_min(ts: Optional[str], jetzt: dt.datetime) -> Optional[float]:
    if not ts:
        return None
    try:
        return (jetzt - dt.datetime.fromisoformat(ts)).total_seconds() / 60
    except ValueError:
        return None


def plane_shops(shops: list[Shop], zustand: dict, jetzt: dt.datetime, einst: dict) -> list[tuple[Shop, str]]:
    """Gestaffelte Prüfung: Händler, die Kaufalarme auslösen dürfen, werden in jedem Lauf SCHNELL geprüft (nur bekannte
    Angebote, je 1 Anfrage) und alle ~30 Min. VOLL (kompletter Katalog, findet neue Produkte). Alle übrigen Händler
    (nur Bericht, kein Alarm) werden nur alle ~2 Std. voll geprüft. Reihenfolge: Alarmfähige zuerst, schnelle vor vollen,
    dann am längsten ungeprüft."""
    voll_alarm = float(einst.get("vollsuche_minuten_alarmfaehig", 30))
    voll_sonst = float(einst.get("vollsuche_minuten_sonstige", 120))
    plan: list[tuple[tuple, Shop, str]] = []
    for sh in shops:
        sz = zustand["shops"].get(sh.id) or {}
        alter_voll = _alter_min(sz.get("letzte_vollsuche"), jetzt)
        alter = _alter_min(sz.get("zuletzt_geprueft"), jetzt)
        grenze = voll_alarm if sh.kaufalarm_freigegeben else voll_sonst
        if alter_voll is None or alter_voll >= grenze:
            modus = "voll"
        elif sh.kaufalarm_freigegeben:
            modus = "schnell"
        else:
            continue   # nicht fällig und ohne Alarmrecht: spart Anfragen
        plan.append(((not sh.kaufalarm_freigegeben, modus == "voll", sz.get("zuletzt_geprueft") or ""), sh, modus))
    plan.sort(key=lambda x: x[0])
    return [(sh, mo) for _, sh, mo in plan]


def fuehre_aus(konfig: Konfig, abrufer, speicher: Speicher, *, testdaten: bool = False,
               jetzt: Optional[dt.datetime] = None, telegram_senden: bool = True,
               telegram_transport: Optional[Callable] = None, log: Callable[[str], None] = print,
               zeitbudget: Optional[float] = None, parallel: int = 1) -> dict:
    """zeitbudget (Sekunden) + parallel > 1: Shops parallel, der am längsten ungeprüfte zuerst; was das Budget sprengt,
    kommt im nächsten Lauf dran. Ohne zeitbudget: alle Shops nacheinander in Konfigurationsreihenfolge."""
    jetzt = jetzt or dt.datetime.now(dt.timezone.utc)
    zeitpunkt = jetzt.replace(microsecond=0).isoformat()
    heute = jetzt.date()
    zustand = speicher.lade_zustand()
    if hasattr(abrufer, "host_zustand") and not testdaten:
        abrufer.host_zustand = zustand["hosts"]
    einstellungen = konfig.produkte.get("allgemein", {})

    alle_beob: list[m.Beobachtung] = []
    alle_ereignisse: list[m.Ereignis] = []
    alle_ausgeschlossen: list[dict] = []
    shop_berichte: dict[str, dict] = {}
    verlauf: list[dict] = []

    shops = [sh for sh in konfig.shops if not ist_ausgeschlossen(sh.basis_url, konfig.ausschluss_domains, konfig.ausschluss_namen)]
    modi: dict[str, str] = {sh.id: "voll" for sh in shops}
    if zeitbudget:  # nur bei der One-Piece-Prüfung: gestaffelte Prüfung (schnelle Runde / Vollsuche)
        plan = plane_shops(shops, zustand, jetzt, einstellungen)
        shops = [sh for sh, _ in plan]
        modi = {sh.id: mo for sh, mo in plan}
    t0 = time.monotonic()
    uebersprungen: list[str] = []
    lock = threading.RLock()

    # Telegram vorab klären: Alarme werden SOFORT nach der Prüfung des jeweiligen Shops gesendet, nicht erst am Laufende
    tg_aktiv, tg_info = telegram.konfiguration()
    if testdaten:
        tg_aktiv, tg_info = False, "Testdaten-Lauf: Telegram wird nie benutzt"
    elif not telegram_senden:
        tg_aktiv, tg_info = False, "Telegram für diesen Lauf abgeschaltet"
    offene = zustand.setdefault("offene_meldungen", [])
    beob_index: dict[str, dict] = {}
    gesendet, fehlgeschlagen = 0, []

    def versende(ereig: list, index: dict) -> None:
        nonlocal gesendet
        for e in ereig:
            if not (e.alarm and not e.unterdrueckt):
                continue
            d = e.als_dict()
            if not tg_aktiv:
                continue   # nicht aktiv: Meldungen nicht aufstauen, nur im Bericht zeigen
            ok, info = telegram.sende(telegram.formatiere(d, index.get(e.angebot_id)), telegram_transport)
            if ok:
                gesendet += 1
                e.gemeldet = True
            else:
                fehlgeschlagen.append(info)
                offene.append(d)   # wird im nächsten Lauf erneut versucht

    def arbeite(shop: Shop):
        if zeitbudget and time.monotonic() - t0 > zeitbudget:
            return None
        log(f"Prüfe {shop.name} ({shop.basis_url}) [{modi.get(shop.id, 'voll')}] …")
        abrufer.setze_host_regeln(shop.host, shop.min_abstand_sekunden, shop.max_anfragen_pro_lauf)
        try:
            res = pruefe_shop(shop, konfig, abrufer, zustand, zeitpunkt, heute, log, modi.get(shop.id, "voll"))
        except Exception as ex:  # ein kaputter Shop darf den Lauf nicht stoppen
            log(f"  ! {shop.name}: {type(ex).__name__}: {ex}")
            res = [], [], {"name": shop.name, "listen_ok": False, "fehler": [f"{type(ex).__name__}: {ex}"],
                           "produkte_gelesen": 0, "kandidaten": 0, "seiten_geprueft": 0}
        with lock:
            verarbeite_shop(shop, res)
        return True

    def verarbeite_shop(shop: Shop, res) -> None:
        beob, aus, bericht = res
        sz = zustand["shops"].setdefault(shop.id, {"basis_erfasst": False})
        ereig_shop: list[m.Ereignis] = []
        for b in beob:
            ereig, geaendert = ev.verarbeite(b, zustand, shop_basis_erfasst=sz["basis_erfasst"],
                                             shop_freigegeben=shop.kaufalarm_freigegeben,
                                             einstellungen=einstellungen, jetzt=jetzt)
            for e_ in ereig:   # Fake-Shop-Überwachung: auffallend billig -> Alarm mit Warnung
                if e_.alarm and e_.typ in (m.RESTOCK, m.NEU_LIEFERBAR, m.NEUE_VORBESTELLUNG):
                    warn = fakecheck.preis_verdacht(zustand, b.ziel_id, b.shop_id, b.preis_cent, b.waehrung)
                    if warn:
                        e_.text = f"{warn}\n{e_.text}"
                        e_.daten["preis_verdacht"] = True
            ereig_shop.extend(ereig)
            if geaendert:
                verlauf.append({"zeit": zeitpunkt, "angebot": b.angebot_id, "shop": shop.id, "ziel": b.ziel_id,
                                "status": b.status, "abruf_ok": b.abruf_ok, "preis_cent": b.preis_cent,
                                "waehrung": b.waehrung, "versand_cent": b.versand_cent, "gesamt_cent": b.gesamt_cent,
                                "sprache": b.sprache, "typ": b.typ, "sicherheit": b.sicherheit, "quelle": b.url,
                                "fehler": b.fehler, "testdaten": testdaten})
        alle_ereignisse.extend(ereig_shop)
        beob_index.update({b.angebot_id: b.als_dict() for b in beob})
        versende(ereig_shop, beob_index)       # sofort melden
        bericht["basis_vorher"] = sz["basis_erfasst"]
        if bericht["listen_ok"] and not sz["basis_erfasst"]:
            sz["basis_erfasst"] = True
            sz["basis_seit"] = zeitpunkt
            bericht["basis_jetzt_erfasst"] = True
        if bericht["listen_ok"] and bericht.get("modus", "voll") == "voll":
            sz["letzte_vollsuche"] = zeitpunkt
        sz["zuletzt_geprueft"] = zeitpunkt
        sz["letzter_fehler"] = bericht["fehler"][-1] if bericht["fehler"] else None
        shop_berichte[shop.id] = bericht
        alle_beob.extend(beob)
        alle_ausgeschlossen.extend(aus)

    if parallel > 1:
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            ergebnisse = list(pool.map(arbeite, shops))
    else:
        ergebnisse = [arbeite(sh) for sh in shops]
    uebersprungen = [sh.id for sh, r in zip(shops, ergebnisse) if r is None]
    if uebersprungen:
        log(f"{len(uebersprungen)} Shops wegen Zeitbudget auf den nächsten Lauf verschoben")

    # Übrig gebliebene (früher fehlgeschlagene) Meldungen erneut versuchen
    if tg_aktiv:
        rest = []
        for e in list(offene):
            if jetzt - dt.datetime.fromisoformat(e["zeitpunkt"]) > dt.timedelta(hours=24):
                continue  # zu alt, nicht mehr nachsenden
            ok, info = telegram.sende(telegram.formatiere(e, beob_index.get(e["angebot_id"])), telegram_transport)
            if ok:
                gesendet += 1
                for x in alle_ereignisse:
                    if x.fingerabdruck == e["fingerabdruck"]:
                        x.gemeldet = True
            else:
                rest.append(e)
        zustand["offene_meldungen"] = rest
    else:
        zustand["offene_meldungen"] = []

    ev.aufraeumen(zustand, jetzt)
    zusammenfassung = {
        "zeit": zeitpunkt, "testdaten": testdaten, "shops": shop_berichte,
        "beobachtungen": len(alle_beob), "ereignisse": [e.als_dict() for e in alle_ereignisse],
        "ausgeschlossen": alle_ausgeschlossen[:400], "telegram": tg_info, "telegram_gesendet": gesendet,
        "telegram_fehler": fehlgeschlagen, "uebersprungen": uebersprungen,
    }
    speicher.verlauf(verlauf, jetzt.strftime("%Y-%m"))
    speicher.ereignisse([e.als_dict() for e in alle_ereignisse])
    speicher.lauf({k: v for k, v in zusammenfassung.items() if k != "ausgeschlossen"})
    zustand["letzter_lauf"] = zusammenfassung
    speicher.speichere_zustand(zustand)
    return zusammenfassung
