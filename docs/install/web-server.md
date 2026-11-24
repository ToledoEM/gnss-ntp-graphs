# Web server

The collector writes a static site to `/var/lib/gnss-ntp-graphs/www`: `index.html`, the scripts and styles, and a `data/` folder of JSON files it rewrites every minute. Any web server that can serve a folder will do. The one special rule: send `data/` with `Cache-Control: no-cache`, so browsers always fetch fresh numbers.

## lighttpd

GPSNTPHomeBridge's full install already runs lighttpd, and `install.sh --web lighttpd` adds an alias next to the bridge's files. The graphs then appear at `http://<host>/graphs/`. The snippet it installs is `deploy/lighttpd-gnss-ntp-graphs.conf`:

```lighttpd
server.modules += ( "mod_setenv" )

alias.url += ( "/graphs/" => "/var/lib/gnss-ntp-graphs/www/" )

$HTTP["url"] =~ "^/graphs/data/" {
    setenv.add-response-header = ( "Cache-Control" => "no-cache" )
}
```

To add it by hand:

```bash
sudo cp deploy/lighttpd-gnss-ntp-graphs.conf /etc/lighttpd/conf-available/89-gnss-ntp-graphs.conf
sudo lighty-enable-mod gnss-ntp-graphs
sudo systemctl reload lighttpd
```

The installer runs `lighttpd -tt` before reloading. If the test fails it disables the alias again and prints `lighttpd config test failed; alias disabled.`

## nginx

Put the contents of `deploy/nginx-gnss-ntp-graphs.conf` inside an existing `server { }` block:

```nginx
location /graphs/ {
    alias /var/lib/gnss-ntp-graphs/www/;
    index index.html;
}
location /graphs/data/ {
    alias /var/lib/gnss-ntp-graphs/www/data/;
    add_header Cache-Control no-cache;
}
```

Install the collector with `--web none` so it does not try to set up lighttpd.

## Built-in server

With no web server on the host, the collector serves the folder itself. `install.sh` turns this on when lighttpd is missing, and the Docker image always uses it.

```toml
[server]
serve = true
bind = "0.0.0.0"
port = 8080
```

It is Python's threaded `http.server`, sends `no-cache` on `data/`, and logs requests only at debug level (`-v`). It has no TLS or authentication, so keep it on your local network.

## Under a different path

The page loads everything with relative URLs, so it works at the site root, under `/graphs/` or under any other prefix without changes.
