# obs-auto-moc

`obs-auto-moc` is a review-first Obsidian MOC compiler for the live PicoClaw vault on pi3.

It does **not** rewrite `notes/MOC.md` by default. A normal run only:

- resolves the live vault path from `~/.config/obsidian-headless/sync/*/config.json`
- scans Markdown notes and frontmatter
- builds a JSONL inventory manifest
- renders a proposal report
- renders a `MOC.preview.md`

Only `build --apply` writes the live `MOC.md`.

## Project layout

- `SKILL.md`: versioned PicoClaw skill copy
- `bin/obs-auto-moc`: local CLI wrapper
- `obs_auto_moc/`: Python implementation
- `tests/`: unit tests

## Runtime assumptions

- Python 3.10+
- `PyYAML` available on the host

The current local and pi3 environments already provide `yaml`.

## Default live paths

- project root: `/home/haman/custom-claw-tools/obs-auto-moc`
- live skill path: `/home/haman/.picoclaw/workspace/skills/obs-auto-moc/SKILL.md`
- live wrapper path: `/home/haman/.picoclaw/workspace/bin/obs-auto-moc`
- artifacts root: `/home/haman/.picoclaw/workspace/notes/claw/moc`
- live preview path: `/home/haman/.picoclaw/workspace/notes/claw/moc/MOC.preview.md`
- live proposal root: `/home/haman/.picoclaw/workspace/notes/claw/moc/proposals`
- live manifest path: `/home/haman/.picoclaw/workspace/notes/claw/moc/index-manifest.jsonl`
- live MOC path: `/home/haman/.picoclaw/workspace/notes/MOC.md`

## Commands

Preview-only build:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc build
```

Show last-run stats:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc stats
```

Apply the rendered preview to the live MOC:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc build --apply
```

## Artifacts

A normal `build` writes:

- `index-manifest.jsonl`
- `last-run.json`
- `MOC.preview.md`
- `proposals/<date>-moc-proposal.md`

The proposal focuses on:

- scan counts
- malformed or incomplete frontmatter
- orphan notes
- hub candidates
- unresolved links
- next-step guidance

## Validation

Run unit tests:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
python3 -m unittest discover -s tests
```

Run a local smoke build against a real vault path:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc build
./bin/obs-auto-moc stats
```

## Design notes

- The scanner prefers frontmatter-driven grouping over folder-driven grouping.
- It still records top-level vault sections so the generated preview stays familiar.
- Malformed notes are reported instead of silently fixed.
- `build` is safe by default; `--apply` is explicit.
