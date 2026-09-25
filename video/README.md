# video

How the [demo video](https://youtu.be/hws8kKtEp44) is made, so it can be re-made whenever the app changes. It films
the live app, voices the script, draws the animated scenes frame by frame and composes its own music, so there is
nothing to license. macOS only (it uses the system voice "Ava (Premium)"), with Google Chrome, ffmpeg and uv.

```bash
node video/make.mjs                    # film the live site, then render video/out/dipper-demo.mp4 and .srt
node video/make.mjs --reuse            # keep the last capture; redo voice, timing, pictures and sound
node video/make.mjs --reuse --stills 12,95   # render single moments to video/out/stills/
node video/thumbnails.mjs              # YouTube (16:9) and Devpost (3:2) thumbnails
node video/gallery.mjs                 # the Devpost image gallery (3:2)
```

| File | Role |
|---|---|
| `story.mjs` | The script: every scene, its narration and timing |
| `capture.mjs` | Drives the live app as a citizen (phone) and as staff (desktop), saving frames and every tap |
| `film.html`, `film.js`, `film.css` | The film: each frame is a pure function of time, drawn from the real stream geometry and the capture |
| `audio.py` | The music, click sounds and narration mix |
| `make.mjs` | Runs it all in order, with parallel renderers |
| `brief.html` | The two-page project brief ([docs/Dipper-project-brief.pdf](../docs/Dipper-project-brief.pdf)) |

Numbers spoken and shown in the live part (checks, outfall, probabilities) are read off the app during capture.
