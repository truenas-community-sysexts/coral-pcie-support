#!/usr/bin/env python3
"""Decide whether an existing release already covers a kernel.

Called by check-releases.yml when a new TrueNAS stable version appears.
Reads the repo's releases on stdin (gh api --paginate: one JSON array per
page, concatenated) and reports what covers the kernel in $NEW_KERNEL for
the driver in $CURRENT_DRIVER:

    promoted <tag>   served by install.sh's stable channel: no build needed,
                     the tracked version may advance.
    pending <tag>    unpromoted stable build awaiting hardware test: no
                     duplicate build, but the tracked version must NOT
                     advance (that consumes the one-shot version-changed
                     event, so deleting the build after a failed hardware
                     test would leave the kernel with no rebuild path).
    (nothing)        no coverage: build.

Preview (BETA/RC) builds never count: they never promote, so the stable
channel never serves them. A k-tag whose body lost the Target kernel row
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


def find_coverage(data, kver, driver):
    """(kind, tag) for the release covering kver, or None."""
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
                return ('promoted', tag)
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

    found = find_coverage(data, os.environ['NEW_KERNEL'],
                          os.environ['CURRENT_DRIVER'])
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
