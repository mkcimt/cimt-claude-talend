# Talend Studio — Diff Noise Filter

Talend Studio writes auto-generated metadata into `.item`, `.properties`, and `.screenshot` files on every save. Most of it is noise that drowns out functional changes. When reviewing branches or commits, filter out the patterns below before judging "what really changed".

## Always-noise patterns

### `.screenshot` files
Binary or near-binary blobs of the job-design preview. They change on every Studio save where the canvas was visible. **Never** carry functional meaning. Drop from diff entirely.

### `.properties` files — `modificationDate` and `productVersion`
Touched on every `.item` save. See [`item-properties-touch.md`](item-properties-touch.md) for why the touch is *required* (TMC's `repository.commit.id` tracking) but the *content* of the touch is noise. Drop these two attribute changes from review.

### UI coordinates and visual attributes inside `.item`
Studio rewrites `posX`, `posY`, `sizeX`, `sizeY`, `offsetLabelX`, `offsetLabelY`, `nodeColor`, `linkColor`, `LABEL_POSITION` whenever components are moved on the canvas. Functionally inert.

### `repositoryStatus`
Internal Studio annotation describing svn/git status. Reflects local checkout state, not job behaviour.

### XML attribute reordering
Studio sometimes reorders attributes within an element without changing values. Diff noise; ignore unless a value actually differs.

### `talend.project` version bumps
The Studio patch level (`<productVersion>`) inside the project descriptor file may bump when developers run different Studio patch levels. Coordinate, not behaviour.

## Functional signal patterns

When filtering noise, keep these — they almost always carry meaning:

| Pattern | Meaning |
|---|---|
| `<elementParameter name="QUERY">` | SQL changed |
| `<elementParameter name="UNIQUE_NAME">` newly introduced / removed | Component added or deleted |
| `<connection ...>` added / removed | Topology change (flow rewiring) |
| `<context name="...">` value change | Per-env config change |
| `<elementParameter name="USE_CONDITIONS">` flipped to/from `true` | Filter activated/deactivated |
| `<nodeData xsi:type="TalendMapper:MapperData">` content change | tMap mappings changed |
| New file under `routines/`, `joblets/`, `routelets/` | New reusable code |
| `metadata/dsrest/*.json` changed | API definition (Swagger) changed |

## When to use this list

The `talend-branch-reviewer` agent applies these filters automatically. When reviewing manually:

1. Strip `.screenshot` from the diff (`git diff -- ':(exclude)*.screenshot'`).
2. For `.properties`, look only at lines that aren't `modificationDate` or `productVersion`.
3. For `.item`, eyeball-filter UI coordinates; focus on the signal patterns above.
4. The Studio version bump in `talend.project` is rarely relevant — note but don't review.

Anything that survives this filter is a candidate for functional review.
