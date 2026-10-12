// Wächter-Dojo – iPhone-Widget für die App "Scriptable" (kostenlos im App Store)
//
// Einrichtung:
//   1. Scriptable installieren und öffnen, oben rechts "+" tippen
//   2. Diesen kompletten Text einfügen, oben den Namen auf "Dojo" ändern, "Fertig"
//   3. Startbildschirm lange drücken -> "+" oben links -> "Scriptable" -> Größe wählen (klein oder mittel) -> hinzufügen
//   4. Widget lange drücken -> "Widget bearbeiten" -> Script: "Dojo"
//
// Liest nur die öffentliche Statusdatei des Wächters (keine Zugangsdaten). Tippen öffnet das Dojo.
// iOS aktualisiert Widgets selbst, meist alle 5–15 Minuten.

const STATUS_URL = "https://raw.githubusercontent.com/TaCTiiCz/OnePieceW-chter/waechter-daten/status.json"
const DOJO_URL = "https://tactiicz.github.io/OnePieceW-chter/"

const FARBE = {
  bg1: new Color("#2a1c12"), bg2: new Color("#120d09"), text: new Color("#f3e6cf"), dim: new Color("#a8977c"),
  acc: new Color("#f0903c"), ok: new Color("#6fd16f"), alarm: new Color("#ff5a44"), warn: new Color("#ffb347"),
  grau: new Color("#9aa4bb"),
}

function zustand(d) {
  const alter = d && d.updated ? (Date.now() - new Date(d.updated).getTime()) / 60000 : 1e9
  if (!d) return ["KEINE VERBINDUNG", FARBE.grau]
  if (d.state === "alert") return ["ALARM", FARBE.alarm]
  if (alter > 30 || d.state === "stale") return ["STEHT?", FARBE.grau]
  if (d.state === "error") return ["PROBLEM", FARBE.warn]
  return ["LÄUFT", FARBE.ok]
}

function vor(iso) {
  if (!iso) return "–"
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (min < 1) return "gerade eben"
  if (min < 60) return `vor ${min} Min`
  const h = Math.floor(min / 60)
  return h < 24 ? `vor ${h} Std` : `vor ${Math.floor(h / 24)} T`
}

function euro(cent) {
  return cent == null ? "?" : (cent / 100).toFixed(2).replace(".", ",") + " €"
}

function zeile(stack, text, groesse, farbe, fett = false, zeilen = 1) {
  const t = stack.addText(text)
  t.font = fett ? Font.boldMonospacedSystemFont(groesse) : Font.monospacedSystemFont(groesse)
  t.textColor = farbe
  t.lineLimit = zeilen
  t.minimumScaleFactor = 0.7
  return t
}

async function lade() {
  try {
    const r = new Request(STATUS_URL + "?t=" + Date.now())
    r.timeoutInterval = 15
    return await r.loadJSON()
  } catch (e) {
    return null
  }
}

async function baue(groesse) {
  const d = await lade()
  const w = new ListWidget()
  const g = new LinearGradient()
  g.colors = [FARBE.bg1, FARBE.bg2]
  g.locations = [0, 1]
  w.backgroundGradient = g
  w.setPadding(12, 12, 12, 12)
  w.url = DOJO_URL
  w.refreshAfterDate = new Date(Date.now() + 5 * 60 * 1000)

  const kopf = w.addStack()
  kopf.centerAlignContent()
  zeile(kopf, "⛩ DOJO", 13, FARBE.acc, true)
  kopf.addSpacer()
  const [wort, farbe] = zustand(d)
  const chip = kopf.addStack()
  chip.backgroundColor = farbe
  chip.cornerRadius = 6
  chip.setPadding(2, 6, 2, 6)
  zeile(chip, wort, 10, new Color("#120d09"), true)

  w.addSpacer(6)
  if (!d) {
    zeile(w, "Statusdatei nicht erreichbar", 11, FARBE.dim, false, 2)
    return w
  }
  zeile(w, `Letzter Lauf ${vor(d.last_run)}`, 10, FARBE.dim)
  w.addSpacer(6)

  // Naruto
  const n = d.naruto || {}
  const nf = n.bestellbar > 0 ? FARBE.alarm : FARBE.text
  zeile(w, `🍥 Naruto: ${n.bestellbar || 0} bestellbar`, 12, nf, true)
  if (n.guenstigste) {
    zeile(w, `ab ${euro(n.guenstigste.preis_cent)} · ${n.guenstigste.shop}`, 10, FARBE.dim)
  }
  w.addSpacer(4)

  // One Piece
  const op = (d.sites || []).filter(s => s.agent === "onepiece")
  const opAlarm = op.find(s => s.status === "restock")
  zeile(w, opAlarm ? `🏴‍☠️ One Piece: ${opAlarm.name}!` : "🏴‍☠️ One Piece: ruhig", 12,
        opAlarm ? FARBE.alarm : FARBE.text, true)
  if (opAlarm && groesse !== "small") zeile(w, opAlarm.detail || "", 10, FARBE.dim, false, 2)

  // Letzte Meldungen (mittel/groß)
  if (groesse !== "small" && (d.events || []).length) {
    w.addSpacer(6)
    const anzahl = groesse === "large" ? 6 : 1
    for (const e of d.events.slice(0, anzahl)) {
      zeile(w, `${vor(e.time)} · ${e.text}`, 9, FARBE.dim, false, 2)
    }
  }
  w.addSpacer()
  return w
}

const groesse = config.widgetFamily || "medium"
const widget = await baue(groesse)
if (config.runsInWidget) {
  Script.setWidget(widget)
} else {
  await widget.presentMedium()
}
Script.complete()
