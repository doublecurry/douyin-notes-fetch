# Batch Export of AI Notes from Douyin Favorites

Batch iterate through videos in a **personal favorites** section of the Douyin web version:

- Export text if `AI notes / AI subtitles / transcripts` exist

- Skip if not

- Export a separate `.txt` file for each video

- Generate an `index.json` list simultaneously

## Requirements

- Python 3.12+

- Playwright installed

- If your browser engine is not installed on the first run, execute:

```powershell
python -m playwright install chromium

```

## Quick Start

### Method 1: Fetch by Favorites Name

```powershell
python .\douyin_ai_notes_export.py --collection-name "your favorites name"

```

### Method 2: Provide the URL of the favorites page or any video page within the favorites

```powershell
python .\douyin_ai_notes_export.py --collection-url "https://www.douyin.com/user/self?from_tab_name=main&showTab=favorite_collection"

```

If you provide a video URL, for example:

```text
https://www.douyin.com/user/self?from_tab_name=main&modal_id=7615277045148405019&showTab=favorite_collection

```

The script will automatically remove `modal_id` and return to the video list page of that collection to continue running.

## Recommended Behavior

Run only the first 3 to confirm the page structure and account status are correct:

```powershell
python .\douyin_ai_notes_export.py --collection-name "your collection name" --limit 3

```

## Script Behavior

1. Start the persistent browser (default directory: `.browser-profile`)

2. Open the Douyin collection entry

3. If you encounter a login/verification code, wait for you to complete it manually in the browser

4. Enter the target collection

5. Automatically scroll and collect all video URLs in the current collection

6. Open the videos one by one

7. Try clicking `AI Notes / AI Subtitles / Text Script / Subtitles`

8. Extract the text and write it locally; skip if there is no valid text

## Output Directory

Default output to:

```text
exports/<collection name>/

```
Includes:

- `0001_<modal_id>.txt`

- `0002_<modal_id>.txt`

- `index.json`

`index.json` records:

- Collection name

- Collection URL

- Total number of videos

- Number of successful exports

- Number of skipped exports

- Status, output file, and reason for failure for each video

## Common parameters

```powershell
python .\douyin_ai_notes_export.py `

--collection-name "Your collection name" `

--output-dir .\exports `

--profile-dir .\.browser-profile `

--limit 10 `

--timeout-ms 2200

```

Explanation:

- `--collection-name`: Click on the collection by visible name; if it fails, it will revert to manual selection.

- `--collection-url`: Directly open the target collection page.

- `--limit`: Only process the first N videos, suitable for trial runs.

- `--timeout-ms`: Click... Waiting time for the page to stabilize after AI Notes

- `--headless`: Headless mode; **not recommended**, as login and CAPTCHA handling are more difficult.

## Notes

- Douyin's page structure changes frequently. The script has implemented multiple fallbacks (DOM + network response text extraction), but further adjustments to the selector may still be needed.

- The safest way to use it is:

- Log in first

- Manually open the target favorites

- Return to the terminal and press Enter to let the script continue

- If some videos do not have an `AI Notes / AI Subtitles` entry, the script will skip it and write the reason in `index.json`.
