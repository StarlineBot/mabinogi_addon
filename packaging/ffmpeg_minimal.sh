#!/usr/bin/env bash
# Run inside the pristine pinned FFmpeg source directory. No external codec libs.
# Optional 3rd argument: prefix with pinned NVENC(ffnvcodec)/AMF headers (MIT, runtime-loaded driver DLLs).
set -euo pipefail
prefix=$1
cross=${2:-}
hwdeps=${3:-}
extra=()
encoders=h264_mf,aac,wrapped_avframe,rawvideo,pcm_s16le
if [[ -n "$cross" ]]; then
  extra+=(--enable-cross-compile --target-os=mingw32 --arch=x86_64 --cross-prefix="$cross")
fi
if [[ -n "$hwdeps" ]]; then
  # pkg-config path list uses ':', so give MSYS a POSIX path; .pc/cflags keep the 'D:/...' form for clang.
  pc_dir="$hwdeps/lib/pkgconfig"
  if command -v cygpath >/dev/null; then pc_dir="$(cygpath -u "$hwdeps")/lib/pkgconfig"; fi
  export PKG_CONFIG_PATH="$pc_dir"
  extra+=(--pkg-config=pkg-config --enable-ffnvcodec --enable-nvenc --enable-amf --extra-cflags="-I$hwdeps/include")
  encoders="h264_nvenc,h264_amf,$encoders"
fi
./configure --prefix="$prefix" "${extra[@]}" \
  --disable-autodetect --disable-gpl --disable-nonfree --disable-version3 \
  --disable-network --disable-devices --disable-avdevice --disable-doc --disable-debug \
  --disable-ffplay --disable-static --enable-shared --disable-x86asm \
  --disable-everything --enable-mediafoundation --enable-d3d11va \
  --enable-encoder="$encoders" \
  --enable-decoder=h264,aac,pcm_s16le,rawvideo \
  --enable-parser=h264,aac --enable-demuxer=mov,rawvideo,wav,concat \
  --enable-muxer=mp4,null,rawvideo,wav --enable-protocol=file,pipe \
  --enable-filter=scale,format,trim,setpts,concat,atrim,asetpts,anull,aresample,aformat,select,aselect,null || {
    result=$?
    # Preserve the compiler failure in CI output before the temporary tree is removed.
    if [[ -f ffbuild/config.log ]]; then tail -n 80 ffbuild/config.log >&2 || true; fi
    exit "$result"
  }
make -j2
make install
