import {
  ButtonItem,
  DropdownItem,
  PanelSection,
  PanelSectionRow,
  SliderField,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useEffect, useState } from "react";
import { FaVideo } from "react-icons/fa";

type StartResult = { ok: boolean; pid?: number; error?: string };
type StatusResult = { running: boolean; pid: number | null };

const isGsrInstalled = callable<[], boolean>("is_gsr_installed");
const checkGstreamer = callable<[], { ok: boolean; missing: string[]; note?: string }>("check_gstreamer");
const getCaptureMode = callable<[], { mode: string; display: string | null }>("get_capture_mode");
const streamStatus = callable<[], StatusResult>("stream_status");
const startStream = callable<[service: string], StartResult>("start_stream");
const stopStream = callable<[], { ok: boolean; error?: string }>("stop_stream");

const getSelectedService = callable<[], string>("get_selected_service");
const setSelectedService = callable<[service: string], void>("set_selected_service");
const getSelectedQuality = callable<[], string>("get_selected_quality");
const setSelectedQuality = callable<[quality: string], void>("set_selected_quality");


const SERVICE_OPTIONS = [
  { data: "twitch", label: "Twitch" },
  { data: "youtube", label: "YouTube" },
  { data: "custom", label: "Custom" },
];

// The order here is the order on the slider. `mbps` is for display only;
// the real bitrates live in QUALITY_PRESETS in main.py.
const QUALITY_OPTIONS = [
  { key: "potato", label: "Potato", mbps: "1" },
  { key: "low", label: "Low", mbps: "2.2" },
  { key: "balanced", label: "Balanced", mbps: "4.5" },
  { key: "high", label: "High", mbps: "6.5" },
  { key: "very_high", label: "Very High", mbps: "8" },
];

function Content() {
  const [installed, setInstalled] = useState<boolean | null>(null);
  const [gstMissing, setGstMissing] = useState<string[]>([]);
  const [gstNote, setGstNote] = useState("");
  const [captureMode, setCaptureMode] = useState<string>("gsr");
  const [service, setService] = useState("twitch");
  const [quality, setQuality] = useState(2);
  const [running, setRunning] = useState(false);
  const [pid, setPid] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    isGsrInstalled().then(setInstalled).catch(() => setInstalled(false));

    checkGstreamer()
      .then((r) => {
        setGstMissing(r.missing);
        setGstNote(r.note ?? "");
      })
      .catch(() => {});    getCaptureMode().then((m) => setCaptureMode(m.mode)).catch(() => {});

    getSelectedService()
      .then((s) => {
        console.log("[Decky Streamer] loaded:", s);
        setService(s);
      })
      .catch((e) => console.error("[Decky Streamer] load failed:", e));

    getSelectedQuality()
      .then((k) => {
        const i = QUALITY_OPTIONS.findIndex((q) => q.key === k);
        if (i >= 0) setQuality(i);
      })
      .catch(() => {});

    streamStatus()
      .then((s) => {
        setRunning(s.running);
        setPid(s.pid);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    // Don't poll while a start/stop is in progress, or it fights with onStart/onStop.
    if (busy) return undefined;

    const timer = setInterval(() => {
      streamStatus()
        .then((s) => {
          if (running && !s.running) {
            setError("Stream ended unexpectedly. Check the plugin's log folder.");
          }
          setRunning(s.running);
          setPid(s.pid);
        })
        .catch(() => {});
    }, 2000);

    // Cleanup: runs when the panel closes or the values below change.
    return () => clearInterval(timer);
  }, [busy, running]);

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

  const onQualityChange = (index: number) => {
    setQuality(index);
    setSelectedQuality(QUALITY_OPTIONS[index].key).catch(() => {});
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

  // Only a problem if we wanna use GStreamer
  const gstBroken = captureMode === "gstreamer" && gstMissing.length > 0;

  const modeMessage =
    captureMode === "gsr"
      ? "External display detected: using GPU Screen Recorder."
      : installed === false
      ? "GPU Screen Recorder not installed: using the PipeWire fallback, performance and quality may be minimally reduced. For an external display, install it from flathub.org in desktop mode."
      : "Handheld mode: using the PipeWire fallback, performance and quality may be minimally reduced.";

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
        <SliderField
          label={`Quality: ${QUALITY_OPTIONS[quality].label} (${QUALITY_OPTIONS[quality].mbps} Mbps)`}
          value={quality}
          min={0}
          max={QUALITY_OPTIONS.length - 1}
          step={1}
          notchCount={QUALITY_OPTIONS.length}
          notchTicksVisible={true}
          showValue={false}
          disabled={running || busy}
          onChange={onQualityChange}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={running || busy || gstBroken} onClick={onStart}>
          Start stream
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={!running || busy} onClick={onStop}>
          Stop stream
        </ButtonItem>
      </PanelSectionRow>
      {gstBroken && (
        <PanelSectionRow>
          <div>
            Handheld streaming isn't available on this system. Missing GStreamer
            components: {gstMissing.join(", ")}. {gstNote}
          </div>
        </PanelSectionRow>
      )}
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