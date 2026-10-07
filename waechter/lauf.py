"""Ein vollständiger Prüflauf über alle konfigurierten Händler."""

from __future__ import annotations

import datetime as dt
from typing import Callable, Optional

from . import modelle as m
from . import ereignisse as ev
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


def baue_beobachtung(shop: Shop, js: dict, v: dict, k: m.Klassifizierung, t: m.Treffer, info: dict,
                     zeitpunkt: str, heute: dt.date) -> m.Beobachtung:
    preis = shopify.preis_cent_aus_js(v)
    waehrungen = info.get("waehrungen", [])
    if waehrungen == [shop.waehrung]:
        waehrung, bestaetigt = shop.waehrung, True
    elif not waehrungen:
        waehrung, bestaetigt = shop.waehrung, False
    else:
        waehrung, bestaetigt = (waehrungen[0] if len(waehrungen) == 1 else None), False
    status, gruende = bestimme_status(
        verfuegbar=v.get("available") if isinstance(v.get("available"), bool) else None,
        bestand_verfolgt=shopify.bestand_verfolgt(v), titel=js.get("title", ""), variante=v.get("title", ""),
        tags=js.get("tags", []) or [], beschreibung=js.get("description", "") or "",
        verkaufsplaene=shopify.verkaufsplaene(js),
        schema_verfuegbarkeit=shopify.schema_verfuegbarkeit(info, v.get("id")), heute=heute)
    if not waehrungen:
        gruende.append("Währung nicht auf der Seite bestätigt (Konfigurationswert verwendet)")
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
                log: Callable[[str], None]) -> tuple[list[m.Beobachtung], list[dict], dict]:
    setnamen = konfig.produkte.get("displays", {}).get("setnamen", {})
    bericht = {"name": shop.name, "listen_ok": False, "fehler": [], "produkte_gelesen": 0,
               "kandidaten": 0, "seiten_geprueft": 0}
    beobachtungen: list[m.Beobachtung] = []
    ausgeschlossen: list[dict] = []

    pause = abrufer.host_pausiert(shop.host)
    if pause:
        bericht["fehler"].append(f"Shop übersprungen: {pause}")
        return beobachtungen, ausgeschlossen, bericht

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

    # 2) Bereits bekannte Angebote, die nicht mehr in der Liste stehen, trotzdem direkt prüfen
    for aid, eintrag in zustand["angebote"].items():
        if not aid.startswith(shop.id + ":"):
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


def fuehre_aus(konfig: Konfig, abrufer, speicher: Speicher, *, testdaten: bool = False,
               jetzt: Optional[dt.datetime] = None, telegram_senden: bool = True,
               telegram_transport: Optional[Callable] = None, log: Callable[[str], None] = print) -> dict:
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

    for shop in konfig.shops:
        if ist_ausgeschlossen(shop.basis_url, konfig.ausschluss_domains, konfig.ausschluss_namen):
            continue  # doppelte Sicherung, konfig.py verhindert das bereits
        log(f"Prüfe {shop.name} ({shop.basis_url}) …")
        abrufer.setze_host_regeln(shop.host, shop.min_abstand_sekunden, shop.max_anfragen_pro_lauf)
        sz = zustand["shops"].setdefault(shop.id, {"basis_erfasst": False})
        beob, aus, bericht = pruefe_shop(shop, konfig, abrufer, zustand, zeitpunkt, heute, log)
        for b in beob:
            ereig, geaendert = ev.verarbeite(b, zustand, shop_basis_erfasst=sz["basis_erfasst"],
                                             shop_freigegeben=shop.kaufalarm_freigegeben,
                                             einstellungen=einstellungen, jetzt=jetzt)
            alle_ereignisse.extend(ereig)
            if geaendert:
                verlauf.append({"zeit": zeitpunkt, "angebot": b.angebot_id, "shop": shop.id, "ziel": b.ziel_id,
                                "status": b.status, "abruf_ok": b.abruf_ok, "preis_cent": b.preis_cent,
                                "waehrung": b.waehrung, "versand_cent": b.versand_cent, "gesamt_cent": b.gesamt_cent,
                                "sprache": b.sprache, "typ": b.typ, "sicherheit": b.sicherheit, "quelle": b.url,
                                "fehler": b.fehler, "testdaten": testdaten})
        bericht["basis_vorher"] = sz["basis_erfasst"]
        if bericht["listen_ok"] and not sz["basis_erfasst"]:
            sz["basis_erfasst"] = True
            sz["basis_seit"] = zeitpunkt
            bericht["basis_jetzt_erfasst"] = True
        sz["zuletzt_geprueft"] = zeitpunkt
        sz["letzter_fehler"] = bericht["fehler"][-1] if bericht["fehler"] else None
        shop_berichte[shop.id] = bericht
        alle_beob.extend(beob)
        alle_ausgeschlossen.extend(aus)

    # Telegram
    tg_aktiv, tg_info = telegram.konfiguration()
    if testdaten:
        tg_aktiv, tg_info = False, "Testdaten-Lauf: Telegram wird nie benutzt"
    elif not telegram_senden:
        tg_aktiv, tg_info = False, "Telegram für diesen Lauf abgeschaltet"
    offene = zustand.setdefault("offene_meldungen", [])
    beob_index = {b.angebot_id: b.als_dict() for b in alle_beob}
    for e in alle_ereignisse:
        if e.alarm and not e.unterdrueckt:
            offene.append(e.als_dict())
    gesendet, fehlgeschlagen = 0, []
    if tg_aktiv:
        rest = []
        for e in offene:
            if jetzt - dt.datetime.fromisoformat(e["zeitpunkt"]) > dt.timedelta(hours=24):
                continue  # zu alt, nicht mehr nachsenden
            ok, info = telegram.sende(telegram.formatiere(e, beob_index.get(e["angebot_id"])), telegram_transport)
            if ok:
                gesendet += 1
                for x in alle_ereignisse:
                    if x.fingerabdruck == e["fingerabdruck"]:
                        x.gemeldet = True
            else:
                fehlgeschlagen.append(info)
                rest.append(e)
        zustand["offene_meldungen"] = rest
    else:
        # nicht aktiv: Meldungen nicht aufstauen, nur im Bericht zeigen
        zustand["offene_meldungen"] = []

    ev.aufraeumen(zustand, jetzt)
    zusammenfassung = {
        "zeit": zeitpunkt, "testdaten": testdaten, "shops": shop_berichte,
        "beobachtungen": len(alle_beob), "ereignisse": [e.als_dict() for e in alle_ereignisse],
        "ausgeschlossen": alle_ausgeschlossen[:400], "telegram": tg_info, "telegram_gesendet": gesendet,
        "telegram_fehler": fehlgeschlagen,
    }
    speicher.verlauf(verlauf, jetzt.strftime("%Y-%m"))
    speicher.ereignisse([e.als_dict() for e in alle_ereignisse])
    speicher.lauf({k: v for k, v in zusammenfassung.items() if k != "ausgeschlossen"})
    zustand["letzter_lauf"] = zusammenfassung
    speicher.speichere_zustand(zustand)
    return zusammenfassung
