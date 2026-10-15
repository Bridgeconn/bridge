import SplashScreen from "./lib/components/SplashScreen.svelte";
import "./index.css";

// #287: the small window shown while the engine starts. The main window loads
// hidden behind it and does the real work (connectEngine); the shell closes
// this one when the main window is revealed.
const splash = new SplashScreen({
  target: document.getElementById("splash")!,
});

export default splash;
