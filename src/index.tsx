import {
  ButtonItem,
  DropdownItem,
  PanelSection,
  PanelSectionRow,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useEffect, useState } from "react";
import { FaVideo } from "react-icons/fa";

type StartResult = { ok: boolean; pid?: number; error?: string };
type StatusResult = { running: boolean; pid: number | null };

const isGsrInstalled = callable<[], boolean>("is_gsr_installed");
const getCaptureMode = callable<[], { mode: string; display: string | null }>("get_capture_mode");
const streamStatus = callable<[], StatusResult>("stream_status");
const startStream = callable<[service: string], StartResult>("start_stream");
const stopStream = callable<[], { ok: boolean; error?: string }>("stop_stream");

const getSelectedService = callable<[], string>("get_selected_service");
const setSelectedService = callable<[service: string], void>("set_selected_service");

const SERVICE_OPTIONS = [
  { data: "twitch", label: "Twitch" },
  { data: "youtube", label: "YouTube" },
  { data: "custom", label: "Custom" },
];

function Content() {
  const [installed, setInstalled] = useState<boolean | null>(null);
  const [captureMode, setCaptureMode] = useState<string>("gsr");
  const [service, setService] = useState("twitch");
  const [running, setRunning] = useState(false);
  const [pid, setPid] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    isGsrInstalled().then(setInstalled).catch(() => setInstalled(false));
    getCaptureMode().then((m) => setCaptureMode(m.mode)).catch(() => {});
    getSelectedService()
      .then((s) => {
        console.log("[Decky Streamer] loaded:", s);
        setService(s);
      })
      .catch((e) => console.error("[Decky Streamer] load failed:", e));
    streamStatus()
      .then((s) => {
        setRunning(s.running);
        setPid(s.pid);
      })
      .catch(() => {});
  }, []);

  const onServiceChange = (opt: any) => {
    console.log("[Decky Streamer] dropdown onChange:", opt);
    const value = typeof opt === "string" ? opt : opt?.data;
    if (typeof value === "string") {
      setService(value);
      setSelectedService(value)
        .then(() => console.log("[Decky Streamer] saved:", value))
        .catch((e) => console.error("[Decky Streamer] save failed:", e));
    }
  };

  const onStart = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await startStream(service);
      if (r.ok) {
        setRunning(true);
        setPid(r.pid ?? null);
      } else {
        setError(r.error ?? "Unknown error");
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const onStop = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await stopStream();
      if (r.ok) {
        setRunning(false);
        setPid(null);
      } else {
        setError(r.error ?? "Could not stop stream");
      }
    } finally {
      setBusy(false);
    }
  };

  const modeMessage =
    captureMode === "gsr"
      ? "External display detected: using GPU Screen Recorder."
      : installed === false
      ? "GPU Screen Recorder not installed: using the PipeWire fallback, performance may be reduced. For an external display, install it from flathub.org in desktop mode."
      : "Handheld mode: using the PipeWire fallback, performance may be reduced.";

  return (
    <PanelSection title="Stream">
      <PanelSectionRow>
        <DropdownItem
          label="Service"
          rgOptions={SERVICE_OPTIONS}
          selectedOption={service}
          disabled={running || busy}
          onChange={onServiceChange}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={running || busy} onClick={onStart}>
          Start stream
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={!running || busy} onClick={onStop}>
          Stop stream
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <div>{running ? `Streaming (pid ${pid})` : "Not streaming"}</div>
      </PanelSectionRow>
      <PanelSectionRow>
        <div>{modeMessage}</div>
      </PanelSectionRow>
      {error && (
        <PanelSectionRow>
          <div>{error}</div>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

export default definePlugin(() => ({
  name: "Decky Streamer",
  titleView: <div className={staticClasses.Title}>Decky Streamer</div>,
  content: <Content />,
  icon: <FaVideo />,
  onDismount() {},
}));