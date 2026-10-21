# haltia-firefox

Firefox for a touch screen and weak hardware: the Lenovo YOGA Tablet 10
(B8000-H) with the [device-lenovo-b8000h](https://github.com/haltia-de/device-lenovo-b8000h)
shell, but usable without it, on top of mobile-config-firefox. This
repository holds no Firefox build, only prefs, stylesheets, autoconfig,
policies and a profile tool; the Alpine package is `haltia-firefox`. It has
no desktop program and no program id. Project-wide decisions (ADRs) and
plans live in [haltia-de/haltia](https://github.com/haltia-de/haltia).

## Layout

- `haltia-lean.js`, `haltia-ram.js`, `zz-haltia-firefox.js`: default prefs,
  installed into Firefox's `browser/defaults/preferences`.
- `haltia-firefox.cfg.in`, `haltia-calm.js`: autoconfig; keeps the on-screen
  keyboard down on a new window.
- `userChrome.css`, `userChrome-shell.css`, `userContent.css`: styles.
- `haltia-firefox-profile`, `haltia-profile-prefs.py`: prepare profiles
  (styles, the managed block in `user.js`, experimental limits; see `--help`).
- `haltia-firefox-configure`, `haltia-policies.py`: write
  `/etc/firefox/policies/policies.json` from mobile-config-firefox's.
- `install.sh`: installs all of it; `packaging/alpine/`: `APKBUILD` and
  post-install/post-upgrade scripts.
- `tests/`: offline checks; `docs/device-validation.md`: the tablet test
  plan; `docs/research/`, `benchmarks/`: dated records, do not rewrite them.

## Run and check from the checkout

```sh
python3 -m unittest discover -s tests -v
HOME=$(mktemp -d) sh haltia-firefox-profile --shell
sh install.sh "$(mktemp -d)" /usr
```

Without an installed share folder `haltia-firefox-profile` uses the files
next to it. Give it a temporary `HOME`: it changes Firefox profiles there.
`install.sh ROOT PREFIX` stages into ROOT; it downloads uBlock Origin Lite
and the Russian language pack (cached in `HALTIA_CACHE`, default `.cache/`)
and checks their sha256.

## Packaging and release

The package is built by `packaging/alpine/APKBUILD`, which runs
`install.sh "$pkgdir" /usr`. A release is a tag `vX.Y.Z` equal to `pkgver`
in `APKBUILD`, with release notes in `NEWS.md`;
`.github/workflows/release.yml` then builds the signed package with
[haltia-de/ci](https://github.com/haltia-de/ci) and attaches it to the
GitHub release. A release needs the user's approval: do not tag on your own.

The old name `b8k-firefox` (before ADR 0004) stays as a package `provides`,
the `b8k-firefox-profile` link and the `b8k.default` profile folder: keep
them until 3.0.

## Conventions

Follow the shared rules in
[haltia-de/haltia docs/conventions.md](https://github.com/haltia-de/haltia/blob/main/docs/conventions.md).
