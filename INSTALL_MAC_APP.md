# Install Cognote On macOS

This guide is for installing and using the packaged `Cognote.app` on a Mac.

It assumes someone has already built the app for you.

## What Cognote does

When you open `Cognote.app`, it:

- starts its own local service automatically
- opens the Cognote interface in a native window
- stores its data under `~/Library/Application Support/Cognote`
- can import Apple Notes into a local SQLite library
- can optionally enable semantic search with an OpenAI API key

You do not need to use Terminal to run the app.

## Before first launch

You should have:

- `Cognote.app`
- an OpenAI API key if you want semantic search enabled

Semantic search is optional. The app still works in keyword mode without the key.

## First launch

1. Open `Cognote.app`.
2. If macOS asks whether Cognote can control Notes, allow it.
3. On the first-run screen, choose whether to enable semantic search.
4. If you enable semantic search, paste the OpenAI API key when prompted.
5. Click the button to import Apple Notes and build the library.

During setup, Cognote will:

- export notes from Apple Notes
- write intermediate export files to Application Support
- create or update the local SQLite database
- generate embeddings for semantic search when an API key is available

The first run may take a while if there are many notes.

## Where Cognote stores data

Cognote stores runtime data here:

- `~/Library/Application Support/Cognote/notes.db`
- `~/Library/Application Support/Cognote/exports/`

Each setup or sync creates a timestamped export snapshot under `exports/`.

## Syncing later

Use the `Sync notes` button inside the app when you want Cognote to refresh from Apple Notes.

During sync:

- new notes are added
- changed notes are updated
- notes missing from Apple Notes are archived locally

Archived notes are hidden from the normal library by default. Use the archive view when you want to inspect them.

## OpenAI key behavior

If you enter an OpenAI key during setup:

- Cognote stores it locally in macOS Keychain
- semantic and hybrid search become available
- the assistant workspace can use OpenAI as well

If you do not enter a key:

- keyword search still works
- semantic search stays disabled

You can update or remove the key later in `Settings`.

## Troubleshooting

### Cognote cannot import notes

Check:

- the Mac is running Apple Notes
- you allowed Cognote to control Notes
- Notes is available under the same macOS user account

If needed, quit Cognote, reopen it, and try setup or sync again.

### Semantic search is unavailable

Check:

- an OpenAI key has been saved in `Settings`
- the key is valid
- the Mac has internet access

### The app opens but shows an empty library

Run the first setup flow, or use `Sync notes` if setup was already completed before.

### macOS blocks the app from opening

If the app is unsigned or not notarized, macOS may warn before opening it. In that case:

- right-click the app
- choose `Open`
- confirm the prompt

## Everyday use

Typical use is simple:

1. Open `Cognote.app`.
2. Search or browse notes.
3. Click `Sync notes` when you want the library refreshed from Apple Notes.

That is the intended normal workflow.
