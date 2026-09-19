#!/usr/bin/env python3
"""Decide whether an existing release already covers a kernel.

Called by check-releases.yml when a new TrueNAS stable version appears.
Reads the repo's releases on stdin (gh api --paginate: one JSON array per
page, concatenated) and reports what covers the kernel in $NEW_KERNEL for
the driver in $CURRENT_DRIVER:

    promoted <tag>   served by install.sh's stable channel: no build needed,
                     the tracked version may advance. It is a promoted
                     (full) release that is also approved for the TrueNAS
                     train of $NEW_VERSION, the rule install.sh selects by: a
                     verified-train marker for that train, or no marker at
                     all (promoted before per-train sign-off). promote.yml
                     writes the marker in the same update that promotes a
                     stable build, so a promoted build is approved for the
                     train it was built for; the check only matters when a
                     kernel is shared across trains.
    pending <tag>    unpromoted stable build awaiting hardware test: no
                     duplicate build, but the tracked version must NOT
                     advance (that consumes the one-shot version-changed
                     event, so deleting the build after a failed hardware
                     test would leave the kernel with no rebuild path).
    (nothing)        no coverage: build.

Preview (BETA/RC) builds never count: they never promote, so the stable
channel never serves them. A promoted build approved for other trains only
does not count either, and is not pending: the installer does not serve it
to this train, and no hardware test for this train will come for it, so the
safe answer is to build. A k-tag whose body lost the Target kernel row
counts only once promoted: unpromoted, it cannot be told apart from a
preview build, and the safe default is to build.

Transition guard: coverage only means "installable" if the installer users
actually run matches by kernel. The README one-liner runs the install.sh
attached to the repo's Latest release ($LATEST_TAG), and only k-tag builds
ship the kernel-aware installer; a v-tag Latest still matches exact TrueNAS
versions and would answer "No stable release found" for the skipped
version. So unless Latest is a k-tag, nothing counts as coverage. An empty
$LATEST_TAG (failed lookup) is treated the same way: the fail-safe
direction is always "build".

Matching rules mirror install.sh's release-selection snippet;
tests/test_kernel_coverage.py holds both to the shared fixtures.
"""
import json
import os
import re
import sys

VT_RE = re.compile(r'^[ \t]*<!--\s*verified-train:\s*([^\s>]+?)\s*-->', re.M)


def train_key(version):
    """Train key of a TrueNAS version, the rule install.sh's
    truenas_train_key applies: the major from 26 on (26.0.0-BETA.3 is 26),
    major.minor before that (25.10.7 is 25.10). '' when there is none."""
    m = re.match(r'(\d+)(?:$|\.(\d*))', version or '')
    if not m:
        return ''
    if int(m.group(1)) >= 26:
        return m.group(1)
    return f'{m.group(1)}.{m.group(2)}' if m.group(2) else ''


def approved_for(release, train):
    """install.sh's approval gate for a promoted release: a verified-train
    marker for the train, or no marker at all (grandfathered)."""
    trains = set(VT_RE.findall(release.get('body') or ''))
    return train in trains if trains else True


def find_coverage(data, kver, driver, train=None):
    """(kind, tag) for the release covering kver, or None. With a train,
    promoted coverage must also be approved for it."""
    short = kver.split('-')[0]
    ker_re = re.compile(r'Target kernel\s*\|\s*`([^`]+)`')
    hdr_re = re.compile(r'for TrueNAS SCALE (\S+)')
    pre_re = re.compile(r'-(BETA|RC)', re.IGNORECASE)

    pending = None
    for r in data:
        if r.get('draft'):
            continue
        tag = r.get('tag_name', '')
        body = r.get('body') or ''
        hdr = hdr_re.search(body)
        if pre_re.search(tag) or (hdr and pre_re.search(hdr.group(1))):
            continue
        # Only builds of the current driver count: a driver bump must
        # rebuild every kernel (the dispatch condition handles that).
        if f'gasket{driver}-' not in tag:
            continue
        m = ker_re.search(body)
        tk = m.group(1) if m else ''
        promoted = not r.get('prerelease')
        # Body row is the primary key; the k-tag fallback needs promoted
        # (see module docstring).
        if tk == kver or (not tk and promoted
                          and tag.startswith(f'k{short}-gasket')):
            if promoted:
                if train is None or approved_for(r, train):
                    return ('promoted', tag)
                continue
            if pending is None:
                pending = tag
    if pending:
        return ('pending', pending)
    return None


def main():
    # gh api --paginate emits one JSON array per page, concatenated.
    decoder = json.JSONDecoder()
    text = sys.stdin.read()
    data = []
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        doc, pos = decoder.raw_decode(text, pos)
        if isinstance(doc, list):
            data.extend(doc)

    # The train the new version belongs to. check-releases.yml always sets
    # NEW_VERSION; a version with no train key cannot be matched to an
    # approval, so it builds.
    train = None
    if 'NEW_VERSION' in os.environ:
        train = train_key(os.environ['NEW_VERSION'])
        if not train:
            print(f"NOTE: no TrueNAS train for version "
                  f"{os.environ['NEW_VERSION']!r}; building.", file=sys.stderr)
            return
    found = find_coverage(data, os.environ['NEW_KERNEL'],
                          os.environ['CURRENT_DRIVER'], train)
    if not found:
        return
    # Transition guard (see module docstring).
    latest = os.environ.get('LATEST_TAG', '')
    if not latest.startswith('k'):
        why = (f'Latest release {latest} predates the kernel-aware installer'
               if latest else 'the Latest release lookup failed')
        print(f'NOTE: {found[0]} coverage by {found[1]} ignored: {why}, so '
              'the one-liner cannot serve this version by kernel match; '
              'building.', file=sys.stderr)
        return
    print(f'{found[0]} {found[1]}')


if __name__ == '__main__':
    main()
