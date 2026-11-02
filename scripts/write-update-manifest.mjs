import { readFile, writeFile } from "node:fs/promises";
import { basename } from "node:path";
import { pathToFileURL } from "node:url";

/** Only a fully signed Windows release is advertised to installed clients. */
export async function writeUpdateManifest({ repository, tag, installer, output, version }) {
  if (!/^[\w.-]+\/[\w.-]+$/.test(repository)) throw new Error("Invalid release repository");
  if (tag !== `v${version}` || !/^\d+\.\d+\.\d+$/.test(version)) {
    throw new Error("Updater manifest requires a stable tag matching the bundled version");
  }
  const signature = (await readFile(`${installer}.sig`, "utf8")).trim();
  if (!signature) throw new Error("Missing updater signature");
  const manifest = {
    version,
    notes: `Bridge ${version}. Release notes: https://github.com/${repository}/releases/tag/${tag}`,
    platforms: {
      "windows-x86_64": {
        signature,
        url: `https://github.com/${repository}/releases/download/${tag}/${encodeURIComponent(basename(installer))}`,
      },
    },
  };
  await writeFile(output, JSON.stringify(manifest, null, 2) + "\n", "utf8");
  return manifest;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [repository, tag, installer, output] = process.argv.slice(2);
  const { version } = JSON.parse(await readFile(new URL("../src-tauri/tauri.conf.json", import.meta.url), "utf8"));
  await writeUpdateManifest({ repository, tag, installer, output, version });
}
