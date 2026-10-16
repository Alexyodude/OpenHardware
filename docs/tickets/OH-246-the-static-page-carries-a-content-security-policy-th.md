---
id: OH-246
title: The static page carries a Content-Security-Policy that Pyodide still runs under
status: open
priority: P3
created: '2026-10-16'
---

From the security review of the static site (OH-243, 2026-10-16), LOW. The hosted page shares the origin https://alexyodude.com with the owner's root site and StoryToVideo's OAuth pages. Uploaded firmware runs in C++ cores inside Pyodide's wasm memory, so a memory-safety bug in a core could become arbitrary Python, then arbitrary JS in the Worker at that origin: no DOM, but same-origin requests and IndexedDB. Defence in depth: a meta CSP in the built index.html, e.g. default-src 'self'; script-src 'self' 'wasm-unsafe-eval' plus hashes of the import map and the inline module; worker-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'. It has to be tested under Pyodide, whose loader may need more. A subdomain would separate the origin outright, but that is a DNS change and the owner's decision. The same review also suggested pinning the workflow's actions to commit SHAs and installing pip packages with --require-hashes; rules.yml pins by tag too, so that is a repository-wide choice rather than this page's. Verify: test_site_browser's samples and boards pass with the CSP in the page, and a test asserts the built page carries it. Claims tools/build_site.py and its tests when taken; OH-243 holds them now.
