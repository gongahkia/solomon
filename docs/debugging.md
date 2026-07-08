# Debugging

Set `SHISA_DEBUG=1` to print a per-render trace to stderr while keeping the prompt on stdout:

```text
[shisa] cwd=/path
[shisa] module=cwd sync 0.12ms cache=none
[shisa] module=git_branch async 0.34ms cache=hit
[shisa] module=language_versions async 1.20ms cache=miss placeholder=true
[shisa] total 3.24ms modules=3
```

Use `SHISA_DEBUG=2` to add cache-key inspection fields:

```text
[shisa] module=git_branch async 0.34ms cache=hit key=module:git_branch age_ms=0 hit_rate=n/a
```

Run a one-off traced render without using the daemon cache:

```sh
shisa trace --cwd /tmp --exit 0 --jobs 0 2>/tmp/shisa-trace.out
```

Trace output is always stderr. Prompt output remains stdout so shell hooks keep working.
