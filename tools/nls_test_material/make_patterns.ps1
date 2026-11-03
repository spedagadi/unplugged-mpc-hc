$ErrorActionPreference = 'Stop'
$ff = 'C:\htpc\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe'
$dir = $PSScriptRoot
if (!(Test-Path $ff)) { throw "ffmpeg not found: $ff" }

& $ff -hide_banner -loglevel error -f lavfi -i "smptebars=size=1440x1080:rate=24000/1001" `
  -vf "pad=1920:1080:240:0:black" -t 12 -c:v libx264 -preset veryfast -crf 18 `
  -pix_fmt yuv420p -movflags +faststart -y "$dir\nls_16x9_pillarbox_4x3.mp4"

& $ff -hide_banner -loglevel error -f lavfi -i "smptebars=size=1920x800:rate=24000/1001" `
  -vf "pad=1920:1080:0:140:black" -t 12 -c:v libx264 -preset veryfast -crf 18 `
  -pix_fmt yuv420p -movflags +faststart -y "$dir\nls_16x9_letterbox_240.mp4"

& $ff -hide_banner -loglevel error -f lavfi -i "smptebars=size=1760x736:rate=24000/1001" `
  -vf "pad=1920:1080:80:172:black" -t 12 -c:v libx264 -preset veryfast -crf 18 `
  -pix_fmt yuv420p -movflags +faststart -y "$dir\nls_16x9_both_239.mp4"

& $ff -hide_banner -loglevel error -f lavfi -i "smptebars=size=2880x2160:rate=24000/1001" `
  -vf "pad=3840:2160:480:0:black" -t 12 -c:v libx264 -preset veryfast -crf 18 `
  -pix_fmt yuv420p -movflags +faststart -y "$dir\nls_4k_pillarbox_4x3.mp4"

Write-Host "NLS test patterns written to $dir"