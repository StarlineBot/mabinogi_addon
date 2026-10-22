#!/usr/bin/env bash
# Run inside the pristine pinned FFmpeg source directory. No external codec libs.
set -euo pipefail
prefix=$1
cross=${2:-}
extra=()
if [[ -n "$cross" ]]; then
  extra+=(--enable-cross-compile --target-os=mingw32 --arch=x86_64 --cross-prefix="$cross")
fi
./configure --prefix="$prefix" "${extra[@]}" \
  --disable-autodetect --disable-gpl --disable-nonfree --disable-version3 \
  --disable-network --disable-devices --disable-avdevice --disable-doc --disable-debug \
  --disable-ffplay --disable-static --enable-shared --disable-x86asm \
  --disable-everything --enable-mediafoundation --enable-d3d11va \
  --enable-encoder=h264_mf,aac,wrapped_avframe,rawvideo,pcm_s16le \
  --enable-decoder=h264,aac,pcm_s16le,rawvideo \
  --enable-parser=h264,aac --enable-demuxer=mov,rawvideo,wav,concat \
  --enable-muxer=mp4,null,rawvideo,wav --enable-protocol=file,pipe \
  --enable-filter=scale,format,trim,setpts,concat,atrim,asetpts,anull,aresample,aformat,select,aselect,null
make -j2
make install
