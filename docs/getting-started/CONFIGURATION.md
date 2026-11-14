# Configuration

Core settings (IFS Cloud URL, OAuth Realm, Client ID) - and, if you need more than one IFS instance or headless `client_credentials` auth, named environments - are covered in **[Managing IFS Environments](ENVIRONMENTS.md)**. This page covers the one remaining optional setting: the Skills Directory.

---

## Skills Directory

By default, skills are stored inside the server's own package folder (`src/ifs_mcp/resources/`). **They can be lost or overwritten when the server is updated** (a `git pull`, a reinstall, or a plugin update).

To keep your skills permanently, set the Skills Directory to a folder on your machine (or a shared git repository) before you start creating skills.

**How to set it:**

Set `SKILLS_DIR` to an absolute path of a folder that already exists, for example `C:\Users\you\Documents\ifs-skills` or `/Users/you/Documents/ifs-skills`. Either:

- add `SKILLS_DIR=...` to a `.env` file in the server's project root (gitignored, read at start-up), or
- set the `SKILLS_DIR` environment variable before launching your AI agent (e.g. in your shell profile).

Don't rely on editing the plugin's own `.mcp.json`: a plugin update replaces it.

**What changes when it's set:**

- `save_skill` and `import_skill` write to your folder instead of inside the package
- `get_api_guide` scans both your folder and the built-in resources - the bundled guides (client navigator, quick reports, OData reference, skill authoring) remain available
- Skills in your folder take precedence over same-named built-in files
- You can version-control or share the folder across your team

---

