# Linux

## inotify limits

Shisa compares its registered watch-path count with `/proc/sys/fs/inotify/max_user_watches` on Linux and logs `inotify_limit_low` or `inotify_limit_exceeded` when the margin is tight.

Check the current limit:

```sh
cat /proc/sys/fs/inotify/max_user_watches
sysctl fs.inotify.max_user_watches
```

Raise it for the current boot:

```sh
sudo sysctl -w fs.inotify.max_user_watches=1048576
```

Make it persistent:

```sh
printf '%s\n' 'fs.inotify.max_user_watches=1048576' | sudo tee /etc/sysctl.d/60-shisa.conf
sudo sysctl --system
```

If the daemon logs `inotify_limit_exceeded`, Shisa still falls back to normal prompt rendering, but filesystem-driven cache invalidation may be incomplete until the limit is raised.
