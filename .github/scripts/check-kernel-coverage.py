#!/usr/bin/env python3
"""Decide whether an existing release already covers a kernel.

Called by check-releases.yml when a new TrueNAS stable version appears.
Reads the repo's releases on stdin (gh api --paginate: one JSON array per
page, concatenated) and reports what covers the kernel in $NEW_KERNEL for
the driver in $CURRENT_DRIVER:

    promoted <tag>   a promoted (non-prerelease) release install.sh's stable
                     channel serves for this kernel: no build is needed and
                     the tracked version may advance.
    pending <tag>    an unpromoted stable build awaiting hardware-test
                     promotion: no duplicate build is needed, but the tracked
                     version must NOT advance. Advancing would consume the
                     one-shot version-changed event, so deleting the build
                     after a failed hardware test would leave the kernel with
                     no rebuild path.
    (nothing)        no coverage: build.

Preview (BETA/RC) builds never provide coverage: they are never promoted, so
install.sh's stable channel never serves them (a GA release reusing the last
RC's kernel still needs its own stable build). A k-tagged release whose body
lost the Target kernel row counts only once promoted: an unpromoted one
cannot be told apart from a preview build, and the safe default is to build.

The matching rules mirror install.sh's release-selection snippet;
tests/test_kernel_coverage.py holds both to the shared release fixtures.
"""
import json
import os
import re
import sys


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

    kver = os.environ['NEW_KERNEL']
    short = kver.split('-')[0]
    driver = os.environ['CURRENT_DRIVER']
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
        # The Target kernel row is the primary key; a k-tag whose body lost
        # the row still encodes its short kernel in the tag, but only counts
        # once promoted (see module docstring).
        if tk == kver or (not tk and promoted
                          and tag.startswith(f'k{short}-gasket')):
            if promoted:
                print(f'promoted {tag}')
                return
            if pending is None:
                pending = tag
    if pending:
        print(f'pending {pending}')


if __name__ == '__main__':
    main()
