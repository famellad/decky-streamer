import { PanelSection, PanelSectionRow, staticClasses } from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useEffect, useState } from "react";
import { FaVideo } from "react-icons/fa";

const isGsrInstalled = callable<[], boolean>("is_gsr_installed");

function Content() {
  // null = still checking
  const [installed, setInstalled] = useState<boolean | null>(null);

  useEffect(() => {
    isGsrInstalled()
      .then(setInstalled)
      .catch(() => setInstalled(false));
  }, []);

  let message: string;

  if (installed === null) {
    message = "Checking for GPU Screen Recorder...";
  } else if (installed) {
    message = "GPU Screen Recorder installed correctly.";
  } else {
    message = "GPU Screen Recorder flatpak not installed, visit flathub.org in desktop mode.";
  }

  return (
    <PanelSection title="GPU Screen Recorder Status">
      <PanelSectionRow>
        <div>{message}</div>
      </PanelSectionRow>
    </PanelSection>
  );
}

export default definePlugin(() => ({
  name: "Decky GSR",
  titleView: <div className={staticClasses.Title}>Decky GSR</div>,
  content: <Content />,
  icon: <FaVideo />,
  onDismount() {},
}));