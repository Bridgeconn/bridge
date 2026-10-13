// The team dashboard's entry (#81): a second Vite build, served by the hub.
import DashboardApp from "./DashboardApp.svelte";

const app = new DashboardApp({ target: document.getElementById("app") as HTMLElement });

export default app;
