import { useState, useEffect, useCallback, useRef } from "react";

const STAGES = [
  { key: "ingest", label: "Ingesting from SD..." },
  { key: "grouping", label: "Clustering sessions..." },
  { key: "dedup", label: "Detecting duplicates..." },
  { key: "sharpness", label: "Scoring sharpness..." },
  { key: "composition", label: "Scoring composition..." },
  { key: "exposure", label: "Scoring exposure..." },
  { key: "naming", label: "Generating names (Florence-2)..." },
  { key: "darktable_sync", label: "Syncing to Darktable..." },
];
const PER_STAGE = [2, 1, 1, 7, 7, 7, 4, 3];
const TOTAL = PER_STAGE.reduce((a, b) => a + b, 0);

function Icon({ name, size = 16, className = "", style = {} }) {
  return (
    <i
      className={`ti ti-${name} ${className}`}
      style={{ fontSize: size, ...style }}
      aria-hidden="true"
    />
  );
}

function Tab({ label, active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        flex: 1,
        textAlign: "center",
        padding: "5px 0",
        fontSize: 11,
        cursor: "pointer",
        background: active ? "var(--color-background-info)" : "var(--color-background-primary)",
        color: active ? "var(--color-text-info)" : "var(--color-text-secondary)",
        fontWeight: active ? 500 : 400,
        border: "none",
        transition: "all 0.15s",
      }}
    >
      {label}
    </button>
  );
}

function StatusRow({ label, value, valueStyle = {} }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
      <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{label}</span>
      <span style={{ fontSize: 12, fontWeight: 500, ...valueStyle }}>{value}</span>
    </div>
  );
}

function Alert({ type, icon, children }) {
  const bg = type === "ok" ? "var(--color-background-success)" : "var(--color-background-warning)";
  const fg = type === "ok" ? "var(--color-text-success)" : "var(--color-text-warning)";
  return (
    <div style={{
      padding: "6px 10px", borderRadius: "var(--border-radius-md)", fontSize: 11,
      display: "flex", alignItems: "flex-start", gap: 6, marginTop: 8,
      background: bg, color: fg,
    }}>
      <Icon name={icon} size={14} style={{ flexShrink: 0, marginTop: 1 }} />
      <span>{children}</span>
    </div>
  );
}

function Btn({ children, primary, danger, disabled, onClick, style = {} }) {
  const base = {
    flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
    gap: 4, padding: "6px 0", fontSize: 12, fontWeight: 500,
    borderRadius: "var(--border-radius-md)", cursor: disabled ? "default" : "pointer",
    transition: "all 0.15s", border: "0.5px solid var(--color-border-secondary)",
    background: "var(--color-background-primary)", color: "var(--color-text-primary)",
    opacity: disabled ? 0.4 : 1, ...style,
  };
  if (primary) {
    base.background = "var(--color-background-info)";
    base.color = "var(--color-text-info)";
    base.borderColor = "var(--color-border-info)";
  }
  if (danger) {
    base.color = "var(--color-text-danger)";
    base.borderColor = "var(--color-border-danger)";
  }
  return <button style={base} disabled={disabled} onClick={onClick}>{children}</button>;
}

// -- INGEST TAB --
function IngestTab({ state, onRun, onDryRun }) {
  const [source, setSource] = useState("/mnt/photon_sd");
  const [cart, setCart] = useState("001");
  const noCart = cart === "none";
  const running = state.phase === "running";

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <label style={{ minWidth: 56, fontSize: 12, color: "var(--color-text-secondary)" }}>Source</label>
          <select value={source} onChange={e => setSource(e.target.value)}
            style={{ flex: 1, fontSize: 12, padding: "4px 6px", background: "var(--color-background-secondary)", border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-md)", color: "var(--color-text-primary)" }}>
            <option value="/mnt/photon_sd">/mnt/photon_sd</option>
            <option value="/home/alex/Photos/import">/home/alex/Photos/import</option>
          </select>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <label style={{ minWidth: 56, fontSize: 12, color: "var(--color-text-secondary)" }}>Cartridge</label>
          <select value={cart} onChange={e => setCart(e.target.value)}
            style={{ flex: 1, fontSize: 12, padding: "4px 6px", background: "var(--color-background-secondary)", border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-md)", color: "var(--color-text-primary)" }}>
            <option value="001">PHOTON-001 (412 GB free)</option>
            <option value="none">No cartridge detected</option>
          </select>
        </div>
      </div>

      <div style={{ display: "flex", gap: 6, margin: "10px 0" }}>
        <Btn primary disabled={noCart || running} onClick={onRun}>
          <Icon name="player-play" size={14} /> Run pipeline
        </Btn>
        <Btn disabled={noCart || running} onClick={onDryRun}>Dry run</Btn>
      </div>

      {state.phase !== "idle" && (
        <div style={{ padding: "8px 10px", borderRadius: "var(--border-radius-md)", background: "var(--color-background-secondary)", marginBottom: 10 }}>
          <StatusRow label="Status" value={state.phase === "running" ? "Running" : "Complete"}
            valueStyle={{ color: state.phase === "running" ? "var(--color-text-info)" : "var(--color-text-success)" }} />
          <StatusRow label="Stage" value={state.stageName} />
          <StatusRow label="Progress" value={`${state.done} / ${TOTAL}`} />
          <div style={{ height: 3, background: "var(--color-border-tertiary)", borderRadius: 2, overflow: "hidden", margin: "6px 0 4px" }}>
            <div style={{ height: "100%", background: "var(--color-text-info)", borderRadius: 2, transition: "width 0.3s", width: `${Math.round((state.done / TOTAL) * 100)}%` }} />
          </div>
          <StatusRow label="Current" value={state.currentLabel}
            valueStyle={{ fontWeight: 400, fontSize: 11, color: "var(--color-text-secondary)" }} />
        </div>
      )}

      {state.summary && (
        <div>
          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>Last run</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 12px", padding: "8px 10px", background: "var(--color-background-secondary)", borderRadius: "var(--border-radius-md)" }}>
            {Object.entries(state.summary).map(([k, v]) => (
              <div key={k} style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>{k}</span>
                <span style={{ fontSize: 12, fontWeight: 500 }}>{v}</span>
              </div>
            ))}
          </div>
          {state.dryRun ? (
            <Alert type="warn" icon="info-circle">Dry run complete. No files written.</Alert>
          ) : (
            <Alert type="ok" icon="circle-check">28 images synced to Darktable. Refresh lighttable to see new imports.</Alert>
          )}
        </div>
      )}
    </div>
  );
}

// -- STATUS TAB --
function StatusTab({ state }) {
  const currentIdx = STAGES.findIndex(s => s.key === state.stageName);
  return (
    <div>
      <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>Pipeline stages</div>
      <div style={{ fontSize: 12, lineHeight: 1.8 }}>
        {STAGES.map((s, i) => {
          const done = state.phase === "done" || i < currentIdx;
          const active = state.phase === "running" && i === currentIdx;
          const pending = !done && !active;
          return (
            <div key={s.key} style={{ display: "flex", alignItems: "center", gap: 6, color: pending ? "var(--color-text-tertiary)" : "var(--color-text-secondary)" }}>
              {done && <Icon name="circle-check" size={14} style={{ color: "var(--color-text-success)" }} />}
              {active && <Icon name="loader" size={14} style={{ color: "var(--color-text-info)", animation: "spin 1s linear infinite" }} />}
              {pending && <Icon name="circle" size={14} />}
              <span style={{ fontWeight: active ? 500 : 400 }}>
                {s.key}{active && state.phase === "running" ? ` (${state.done}/${TOTAL})` : ""}
              </span>
            </div>
          );
        })}
      </div>
      <div style={{ height: 0.5, background: "var(--color-border-tertiary)", margin: "10px 0" }} />
      <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>Warnings</div>
      <Alert type="warn" icon="alert-triangle">
        IMG_0017.jpg: sharpness 0.09 (below 0.15 threshold)
      </Alert>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

// -- CARTRIDGE TAB --
function CartridgeTab() {
  const [ejecting, setEjecting] = useState(false);
  const [ejectStep, setEjectStep] = useState(0);

  const doEject = () => {
    setEjecting(true);
    setEjectStep(1);
    setTimeout(() => setEjectStep(2), 600);
    setTimeout(() => { setEjectStep(3); setEjecting(false); }, 1200);
  };

  return (
    <div>
      <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>PHOTON-001</div>
      <div style={{ padding: "8px 10px", borderRadius: "var(--border-radius-md)", background: "var(--color-background-secondary)", marginBottom: 10 }}>
        <StatusRow label="Label" value="PHOTON-001" />
        <StatusRow label="Mount" value="/mnt/photon_ssd/001" valueStyle={{ fontSize: 11 }} />
        <StatusRow label="Capacity" value="500 GB" />
        <StatusRow label="Free" value="412 GB (82%)" valueStyle={{ color: "var(--color-text-success)" }} />
        <StatusRow label="Images" value="2,847" />
        <StatusRow label="DB integrity" value="OK" valueStyle={{ color: "var(--color-text-success)" }} />
      </div>
      <div style={{ display: "flex", gap: 6, margin: "10px 0" }}>
        <Btn onClick={() => {}}>
          <Icon name="plus" size={14} /> Init new
        </Btn>
        <Btn danger disabled={ejecting} onClick={doEject}>
          {ejecting ? <Icon name="loader" size={14} style={{ animation: "spin 1s linear infinite" }} /> : <Icon name="logout" size={14} />}
          {ejecting ? "Ejecting..." : "Safe eject"}
        </Btn>
      </div>
      {ejectStep >= 1 && ejectStep < 3 && (
        <div style={{ padding: "8px 10px", borderRadius: "var(--border-radius-md)", background: "var(--color-background-secondary)", marginTop: 8, fontSize: 11, color: "var(--color-text-secondary)" }}>
          <div>Flushing SQLite WAL... {ejectStep >= 2 && <span style={{ color: "var(--color-text-success)" }}>OK</span>}</div>
          {ejectStep >= 2 && <div>Syncing filesystem... <span style={{ color: "var(--color-text-success)" }}>OK</span></div>}
        </div>
      )}
      {ejectStep === 3 && (
        <Alert type="ok" icon="circle-check">PHOTON-001 safely ejected. You may remove the drive.</Alert>
      )}
    </div>
  );
}

// -- MAIN PANEL --
export default function PhotonForgePanel() {
  const [tab, setTab] = useState("ingest");
  const [state, setState] = useState({
    phase: "idle", stageName: "--", done: 0, currentLabel: "--", summary: null, dryRun: false,
  });
  const timerRef = useRef(null);

  const runSim = useCallback((dry = false) => {
    if (timerRef.current) clearInterval(timerRef.current);
    setState({ phase: "running", stageName: "ingest", done: 0, currentLabel: STAGES[0].label, summary: null, dryRun: dry });

    if (dry) {
      setTimeout(() => {
        setState({
          phase: "done", stageName: "darktable_sync", done: TOTAL, currentLabel: "--", dryRun: true,
          summary: { Total: "32", Dupes: "4", Scored: "28", XMP: "0", "DB rows": "0", Elapsed: "12.3s" },
        });
      }, 1500);
      return;
    }

    let stageIdx = 0;
    let step = 0;
    timerRef.current = setInterval(() => {
      if (stageIdx >= STAGES.length) {
        clearInterval(timerRef.current);
        setState(prev => ({
          ...prev, phase: "done", stageName: "darktable_sync", done: TOTAL, currentLabel: "--",
          summary: { Total: "32", Dupes: "4", Scored: "28", XMP: "28", "DB rows": "28", Elapsed: "41.2s" },
        }));
        return;
      }
      step++;
      let totalDone = 0;
      for (let i = 0; i < stageIdx; i++) totalDone += PER_STAGE[i];
      totalDone += Math.min(step, PER_STAGE[stageIdx]);

      setState(prev => ({
        ...prev, stageName: STAGES[stageIdx].key, done: totalDone, currentLabel: STAGES[stageIdx].label,
      }));

      if (step >= PER_STAGE[stageIdx]) { stageIdx++; step = 0; }
    }, 400);
  }, []);

  useEffect(() => () => { if (timerRef.current) clearInterval(timerRef.current); }, []);

  return (
    <div style={{ display: "flex", justifyContent: "center", padding: "1rem 0" }}>
      <div style={{ background: "var(--color-background-secondary)", borderRadius: "var(--border-radius-lg)", padding: "20px 16px", maxWidth: 360, width: "100%" }}>
        <div style={{ maxWidth: 320, fontSize: 13, color: "var(--color-text-primary)" }}>

          {/* Header */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, paddingBottom: 10, borderBottom: "0.5px solid var(--color-border-tertiary)", marginBottom: 10 }}>
            <Icon name="camera" size={18} style={{ color: "var(--color-text-info)" }} />
            <span style={{ fontWeight: 500, fontSize: 14 }}>PHOTONForge</span>
            <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginLeft: "auto" }}>v0.6</span>
          </div>

          {/* Tabs */}
          <div style={{ display: "flex", marginBottom: 10, border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-md)", overflow: "hidden" }}>
            <Tab label="Ingest" active={tab === "ingest"} onClick={() => setTab("ingest")} />
            <Tab label="Status" active={tab === "status"} onClick={() => setTab("status")} />
            <Tab label="Cartridge" active={tab === "cartridge"} onClick={() => setTab("cartridge")} />
          </div>

          {tab === "ingest" && <IngestTab state={state} onRun={() => runSim(false)} onDryRun={() => runSim(true)} />}
          {tab === "status" && <StatusTab state={state} />}
          {tab === "cartridge" && <CartridgeTab />}
        </div>

        <div style={{
          fontSize: 11, color: "var(--color-text-tertiary)", textAlign: "center", marginTop: 12,
          padding: "4px 8px", border: "0.5px dashed var(--color-border-tertiary)", borderRadius: "var(--border-radius-md)",
        }}>
          <Icon name="info-circle" size={12} /> Interactive mockup -- click "Run pipeline" to simulate
        </div>
      </div>
    </div>
  );
}
