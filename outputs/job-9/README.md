# Products building: every finished job, ready to download

A **Products** page with a glowing green **checkmark-shaped building** on top. Below it you get
your **latest product**, then **all previous products**. Each one has a download button for every
file, plus **Download all (.zip)**. You never have to open GitHub.

**Open it:** https://gmoneydakota.github.io/my-city/outputs/job-9/
(Bookmark it or use "Add to Home Screen" on your phone.)

## What you can do on the page
- **⬇** next to any file downloads it straight to your phone or computer (spreadsheets, `.csv`, `.py`, `.json`, models, and so on).
- **⬇ Download all (.zip)** bundles a whole job's files into one zip.
- **👁** previews a file in place. CSV spreadsheets show up as a table (first 200 rows).
- **📄 What is this?** shows the job's README (what was made and how to use it).
- **▶ Open it** / **🧊 CAD Studio** show up when a job built a web page or a 3D model.
- The search box filters by product name, request, or file name. **↻** checks for new products.
- New jobs show up on their own, with no extra setup. Spreadsheets are listed first in each job.

## How it works (no server)
- The page reads the list of files from GitHub's public API: one call lists every file under
  `outputs/job-*`, and a second call gets the job names. If you saved a token in the city's ⚙ Settings,
  the page uses that token too (both pages live on the same site, so they share the setting).
- Downloads come from your city's own website (`gmoneydakota.github.io`), not from github.com.
- If GitHub's API is busy (60 calls/hour without a token), the page falls back to `manifest.json`,
  a saved snapshot of the file list. Downloads still work in that case, and it still finds the READMEs of newer jobs.
- A just-finished job can take about 1 minute to appear, while GitHub Pages republishes the site.

## Putting the checkmark building *in the city map* (one extra step)
Unattended jobs may only write inside `outputs/job-9/`, so I couldn't change the city's
`index.html` myself. The change is ready and tested in `city-upgrade.patch`. It adds a green checkmark
tower labelled **✔ Products** next to the Lucky Tower, with small parcels circling it. Click or tap it
and the Products page opens. Pick either way to apply it:

1. **From the city (easiest):** go to **Make → 🏗 Upgrade city** and send:
   > Apply the patch in outputs/job-9/city-upgrade.patch to index.html (git apply) so the ✔ Products checkmark building appears in the city and opens outputs/job-9/ when clicked. Change nothing else.
   
   Then approve the pull request it opens.
2. **By hand:** in a clone of the repo, run `git apply outputs/job-9/city-upgrade.patch`, then commit and push.

Until you apply it, use the link above (or bookmark it).

## Files
| File | What it is |
|---|---|
| `index.html` | The Products page (checkmark building + downloads). Static, works on phones. |
| `manifest.json` | Saved snapshot of all job files, used only when GitHub's API can't be reached. |
| `build_manifest.py` | Rebuilds the snapshot: `python3 outputs/job-9/build_manifest.py` (optional; the live list doesn't need it). |
| `city-upgrade.patch` | Adds the ✔ Products checkmark building to the 3D city map. |

## Assumptions
- "Products" = everything in each `outputs/job-N/` folder. Bookkeeping files (`job.json`, `PROGRESS.md`,
  `upgrade.json`) are tucked under "Other files" and left out of the zip.
- City upgrade jobs are listed too, with a 🏗 badge, but they never count as the "Latest product". This page itself (job 9) doesn't either.
- When a job's README has a clear title, that title names the product, and your original request is shown underneath.
- Tested on 31 Oct 2026 in headless Chrome at phone width, both live and with GitHub's API blocked:
  downloads, zip, preview, and README all worked. The patched city loaded with no errors, and clicking
  ✔ Products opened this page.
