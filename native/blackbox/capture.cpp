// Original implementation using Windows SDK APIs. No desktop/monitor capture path.
// ABI calls for one handle must be serialized on its creating MTA worker thread.
#include <windows.h>
#include <d3d11.h>
#include <windows.graphics.capture.interop.h>
#include <windows.graphics.directx.direct3d11.interop.h>
#include <winrt/base.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Graphics.h>
#include <winrt/Windows.Graphics.Capture.h>
#include <winrt/Windows.Graphics.DirectX.h>
#include <winrt/Windows.Graphics.DirectX.Direct3D11.h>
#include <winrt/Windows.Foundation.Metadata.h>
#include <winrt/Windows.Security.Authorization.AppCapabilityAccess.h>
#include <atomic>
#include <memory>
#include <cstring>
using namespace winrt;
using namespace winrt::Windows::Graphics::Capture;
using namespace winrt::Windows::Graphics::DirectX;
using namespace winrt::Windows::Graphics::DirectX::Direct3D11;
#define BB extern "C" __declspec(dllexport)

// GPU 축소 실패 전용 코드. 호출자는 CPU 축소로 대체하지 않고 안내 후 중단한다.
constexpr HRESULT BB_E_GPU_SCALE = MAKE_HRESULT(SEVERITY_ERROR, FACILITY_ITF, 0x0201);

// 비율 유지 맞춤. 상한 이하는 원본 그대로(확대 없음), 축소 결과는 짝수 크기.
// Python mabinogi_addon.system.blackbox_capture.fit_output 과 같은 정수 계산이어야 한다.
static void fit_output(int w, int h, int max_w, int max_h, int* out_w, int* out_h) {
    if (w <= max_w && h <= max_h) { *out_w = w; *out_h = h; return; }
    long long ow = max_w, oh = (long long)h * max_w / w;
    if (oh > max_h) { oh = max_h; ow = (long long)w * max_h / h; }
    *out_w = (int)(ow & ~1LL); *out_h = (int)(oh & ~1LL);
    if (*out_w < 2) *out_w = 2;
    if (*out_h < 2) *out_h = 2;
}

// 프레임 형식(bb_frame_format). NV12는 GPU에서 색 변환까지 마친 4:2:0(Y 평면 + UV 교차 평면, 프레임당 w*h*3/2바이트).
constexpr int BB_FORMAT_BGRA = 0, BB_FORMAT_NV12 = 1;

// 캡처 텍스처를 CPU로 복사하기 전에 GPU(D3D11 비디오 프로세서)에서 출력 크기로 줄인다.
// 블랙박스 11.4: NV12 출력이면 크기가 같아도 이 경로로 BGRA→NV12(BT.709, 16~235)를 GPU에서 끝낸다.
// 그러면 CPU로 넘기는 양이 절반 이하가 되고 ffmpeg의 CPU 색 변환(SIMD 없는 빌드라 무거움)이 사라진다.
struct Scaler {
    int in_w{}, in_h{}, format{-1};
    com_ptr<ID3D11VideoDevice> video_device;
    com_ptr<ID3D11VideoContext> video_context;
    com_ptr<ID3D11VideoProcessorEnumerator> enumerator;
    com_ptr<ID3D11VideoProcessor> processor;
    com_ptr<ID3D11Texture2D> input, output, staging;
    com_ptr<ID3D11VideoProcessorInputView> input_view;
    com_ptr<ID3D11VideoProcessorOutputView> output_view;
};

// Windows 11 캡처 노란 테두리 끄기 결과(영상에는 안 찍히지만 게임 창에 계속 보임).
// 0 미확인, 1 끔, 2 API 없음(구버전 Windows), 3 권한 거부, 4 예외. 실패해도 녹화는 계속한다.
static std::atomic<int> g_border_status{0};
static std::atomic<int> g_border_access{-1};  // RequestAccessAsync 결과 캐시(AppCapabilityAccessStatus)

static void disable_capture_border(GraphicsCaptureSession const& session) {
    using winrt::Windows::Foundation::Metadata::ApiInformation;
    using winrt::Windows::Security::Authorization::AppCapabilityAccess::AppCapabilityAccessStatus;
    try {
        if (!ApiInformation::IsPropertyPresent(L"Windows.Graphics.Capture.GraphicsCaptureSession", L"IsBorderRequired")) {
            g_border_status = 2;
            return;
        }
        if (g_border_access < 0)  // 호출 스레드는 MTA(RoInitialize 1)라 동기 대기해도 된다
            g_border_access = int(GraphicsCaptureAccess::RequestAccessAsync(GraphicsCaptureAccessKind::Borderless).get());
        if (g_border_access != int(AppCapabilityAccessStatus::Allowed)) {
            g_border_status = 3;
            return;
        }
        session.IsBorderRequired(false);
        g_border_status = 1;
    } catch (...) {
        g_border_status = 4;
    }
}

BB int __cdecl bb_border_status() { return g_border_status.load(); }

struct Capture;
thread_local Capture* active_capture = nullptr;
void CALLBACK foreground_event(HWINEVENTHOOK, DWORD, HWND, LONG, LONG, DWORD, DWORD);
struct Capture {
    HWND hwnd{};
    HWINEVENTHOOK hook{};
    bool invalidated = false;
    DWORD pid{};
    HANDLE process{};
    ULONGLONG created{};
    com_ptr<ID3D11Device> device;
    com_ptr<ID3D11DeviceContext> context;
    Direct3D11CaptureFramePool pool{nullptr};
    GraphicsCaptureSession session{nullptr};
    IDirect3DDevice frame_device{nullptr};
    int width{}, height{};
    // 0이면 축소·입력 제한 없음(기존 동작: 크기 변경 시 새 형식 필요).
    int max_out_w{}, max_out_h{}, max_in_w{}, max_in_h{};
    int out_w{}, out_h{};  // 첫 프레임에서 정하고 녹화 중 고정
    Scaler scaler;
    // 블랙박스 11.4: NV12 요청(bb_set_format)·실제 형식. 비디오 프로세서가 NV12 출력을 못 하면 BGRA로 내린다.
    bool want_nv12 = false, nv12_failed = false;
    int frame_format = BB_FORMAT_BGRA;
    com_ptr<ID3D11Texture2D> copy_staging;  // 축소 없는 BGRA 복사용(프레임마다 새로 만들지 않음)
    UINT copy_w{}, copy_h{};
    ~Capture() {
        if (active_capture == this) active_capture = nullptr;
        if (hook) UnhookWinEvent(hook);
        try { if (session) session.Close(); if (pool) pool.Close(); } catch (...) {}
        if (process) CloseHandle(process);
    }
    bool valid() {
        DWORD current{};
        GetWindowThreadProcessId(hwnd, &current);
        FILETIME c{}, e{}, k{}, u{};
        return !invalidated && IsWindow(hwnd) && current == pid && WaitForSingleObject(process, 0) == WAIT_TIMEOUT &&
            GetProcessTimes(process, &c, &e, &k, &u) &&
            ((ULONGLONG(c.dwHighDateTime) << 32) | c.dwLowDateTime) == created;
    }
};

// 게임 창이 뒤에 있어도(최소화 아님) 녹화한다(2026-10-23 사용자 결정). WGC 창 캡처는 그 창 내용만 받으므로
// 위에 겹친 다른 창은 영상에 섞이지 않는다. 최소화되면 이 캡처를 닫고 복원 때 새로 연다.
void CALLBACK foreground_event(HWINEVENTHOOK, DWORD, HWND hwnd, LONG, LONG, DWORD, DWORD) {
    if (active_capture && hwnd == active_capture->hwnd) active_capture->invalidated = true;
}
void pump_capture_events() {
    MSG message{};
    while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
        TranslateMessage(&message); DispatchMessageW(&message);
    }
}

bool capture_epoch_active(HWND hwnd) {
    pump_capture_events();
    return active_capture && active_capture->hwnd == hwnd && active_capture->valid();
}

static HRESULT scale_frame(Capture& c, ID3D11Texture2D* source, int cw, int ch, int format) noexcept {
    auto& s = c.scaler;
    try {
        if (!s.processor || s.in_w != cw || s.in_h != ch || s.format != format) {
            s = Scaler{};
            s.video_device = c.device.as<ID3D11VideoDevice>();
            s.video_context = c.context.as<ID3D11VideoContext>();
            D3D11_VIDEO_PROCESSOR_CONTENT_DESC content{};
            content.InputFrameFormat = D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
            content.InputFrameRate = {60, 1};
            content.InputWidth = UINT(cw); content.InputHeight = UINT(ch);
            content.OutputFrameRate = {60, 1};
            content.OutputWidth = UINT(c.out_w); content.OutputHeight = UINT(c.out_h);
            content.Usage = D3D11_VIDEO_USAGE_PLAYBACK_NORMAL;
            check_hresult(s.video_device->CreateVideoProcessorEnumerator(&content, s.enumerator.put()));
            UINT support = 0;
            check_hresult(s.enumerator->CheckVideoProcessorFormat(DXGI_FORMAT_B8G8R8A8_UNORM, &support));
            if (!(support & D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_INPUT))
                return E_NOTIMPL;
            const DXGI_FORMAT out_format = format == BB_FORMAT_NV12 ? DXGI_FORMAT_NV12 : DXGI_FORMAT_B8G8R8A8_UNORM;
            if (format == BB_FORMAT_NV12) {
                support = 0;
                check_hresult(s.enumerator->CheckVideoProcessorFormat(out_format, &support));
            }
            if (!(support & D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_OUTPUT))
                return E_NOTIMPL;
            check_hresult(s.video_device->CreateVideoProcessor(s.enumerator.get(), 0, s.processor.put()));
            D3D11_TEXTURE2D_DESC t{};
            t.Width = UINT(cw); t.Height = UINT(ch); t.MipLevels = 1; t.ArraySize = 1;
            t.Format = DXGI_FORMAT_B8G8R8A8_UNORM; t.SampleDesc.Count = 1;
            t.Usage = D3D11_USAGE_DEFAULT; t.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
            check_hresult(c.device->CreateTexture2D(&t, nullptr, s.input.put()));
            D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC in_view{};
            in_view.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
            check_hresult(s.video_device->CreateVideoProcessorInputView(
                s.input.get(), s.enumerator.get(), &in_view, s.input_view.put()));
            t.Width = UINT(c.out_w); t.Height = UINT(c.out_h);
            t.Format = out_format;
            t.BindFlags = D3D11_BIND_RENDER_TARGET;
            check_hresult(c.device->CreateTexture2D(&t, nullptr, s.output.put()));
            D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC out_view{};
            out_view.ViewDimension = D3D11_VPOV_DIMENSION_TEXTURE2D;
            check_hresult(s.video_device->CreateVideoProcessorOutputView(
                s.output.get(), s.enumerator.get(), &out_view, s.output_view.put()));
            t.Usage = D3D11_USAGE_STAGING; t.BindFlags = 0; t.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
            check_hresult(c.device->CreateTexture2D(&t, nullptr, s.staging.put()));
            RECT src{0, 0, cw, ch}, dst{0, 0, c.out_w, c.out_h};
            s.video_context->VideoProcessorSetStreamFrameFormat(s.processor.get(), 0, D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE);
            s.video_context->VideoProcessorSetStreamSourceRect(s.processor.get(), 0, TRUE, &src);
            s.video_context->VideoProcessorSetStreamDestRect(s.processor.get(), 0, TRUE, &dst);
            s.video_context->VideoProcessorSetOutputTargetRect(s.processor.get(), TRUE, &dst);
            // 드라이버 자동 보정(잡음 제거·선명화 등)은 끈다. 녹화는 게임 화면 그대로여야 한다.
            s.video_context->VideoProcessorSetStreamAutoProcessingMode(s.processor.get(), 0, FALSE);
            D3D11_VIDEO_PROCESSOR_COLOR_SPACE input_space{};  // 캡처 BGRA: RGB 전체 범위(0~255)
            input_space.RGB_Range = 0;
            s.video_context->VideoProcessorSetStreamColorSpace(s.processor.get(), 0, &input_space);
            D3D11_VIDEO_PROCESSOR_COLOR_SPACE output_space{};  // NV12: BT.709 행렬, 제한 범위(16~235) — ffmpeg 입력 표시와 같게
            output_space.YCbCr_Matrix = 1;
            output_space.Nominal_Range = D3D11_VIDEO_PROCESSOR_NOMINAL_RANGE_16_235;
            s.video_context->VideoProcessorSetOutputColorSpace(s.processor.get(), &output_space);
            s.in_w = cw; s.in_h = ch; s.format = format;
        }
        D3D11_BOX box{0, 0, 0, UINT(cw), UINT(ch), 1};
        c.context->CopySubresourceRegion(s.input.get(), 0, 0, 0, 0, source, 0, &box);
        D3D11_VIDEO_PROCESSOR_STREAM stream{};
        stream.Enable = TRUE;
        stream.pInputSurface = s.input_view.get();
        check_hresult(s.video_context->VideoProcessorBlt(s.processor.get(), s.output_view.get(), 0, 1, &stream));
        c.context->CopyResource(s.staging.get(), s.output.get());
        return S_OK;
    } catch (...) {
        s = Scaler{};
        return to_hresult();
    }
}

// max_out_*: 출력 상한(이 안으로 GPU 축소). max_in_*: 받아들일 입력 상한. 모두 0이면 축소 없음.
BB HRESULT __cdecl bb_open_fit(HWND hwnd, DWORD pid, ULONGLONG created, int cursor,
                              int max_out_w, int max_out_h, int max_in_w, int max_in_h, void** output) {
    if (!output) return E_POINTER;
    *output = nullptr;
    bool legacy = !max_out_w && !max_out_h && !max_in_w && !max_in_h;
    if (!legacy && (max_out_w < 2 || max_out_h < 2 || max_in_w < max_out_w || max_in_h < max_out_h))
        return E_INVALIDARG;
    try {
        auto c = std::make_unique<Capture>();
        c->hwnd = hwnd; c->pid = pid; c->created = created;
        c->max_out_w = max_out_w; c->max_out_h = max_out_h;
        c->max_in_w = max_in_w; c->max_in_h = max_in_h;
        c->process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, pid);
        if (!c->process || !c->valid() || IsIconic(hwnd))
            return E_ACCESSDENIED;
        if (!GraphicsCaptureSession::IsSupported()) return E_NOTIMPL;
        auto factory = get_activation_factory<GraphicsCaptureItem, IGraphicsCaptureItemInterop>();
        GraphicsCaptureItem item{nullptr};
        check_hresult(factory->CreateForWindow(hwnd, guid_of<GraphicsCaptureItem>(), put_abi(item)));
        check_hresult(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
            D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0, D3D11_SDK_VERSION,
            c->device.put(), nullptr, c->context.put()));
        auto dxgi = c->device.as<IDXGIDevice>();
        com_ptr<IInspectable> inspectable;
        check_hresult(CreateDirect3D11DeviceFromDXGIDevice(dxgi.get(), inspectable.put()));
        auto size = item.Size();
        if (size.Width <= 0 || size.Height <= 0) return E_INVALIDARG;
        c->width = size.Width; c->height = size.Height;
        c->frame_device = inspectable.as<IDirect3DDevice>();
        c->pool = Direct3D11CaptureFramePool::CreateFreeThreaded(
            c->frame_device, DirectXPixelFormat::B8G8R8A8UIntNormalized, 2, size);
        c->session = c->pool.CreateCaptureSession(item);
        // Unsupported cursor control fails; do not silently adopt a different policy.
        c->session.IsCursorCaptureEnabled(cursor != 0);
        disable_capture_border(c->session);  // 실패해도 녹화는 계속(표시 문제)
        if (active_capture) return E_UNEXPECTED;
        active_capture = c.get();
        c->hook = SetWinEventHook(EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZESTART, nullptr,
                                 foreground_event, 0, 0, WINEVENT_OUTOFCONTEXT);
        if (!c->hook) return HRESULT_FROM_WIN32(GetLastError());
        c->session.StartCapture();
        *output = c.release();
        return S_OK;
    } catch (...) { return to_hresult(); }
}

// S_FALSE: no frame. E_ACCESSDENIED: minimized/identity changed; caller closes and recreates.
// 축소 모드: 출력은 첫 프레임에서 정한 크기로 고정한다. 창 크기가 바뀌면 프레임 풀만 새 크기로
// 다시 만들고 같은 출력 크기로 계속 축소한다. 입력 상한 초과는 ERROR_NOT_SUPPORTED(크기 보고),
// GPU 축소 실패는 BB_E_GPU_SCALE. 축소 없음 모드는 기존대로 크기 변경 시 ERROR_RETRY.
BB HRESULT __cdecl bb_read(void* handle, BYTE* destination, UINT64 capacity,
                          int* width, int* height, INT64* timestamp100ns) {
    if (!handle || !destination || !width || !height || !timestamp100ns) return E_POINTER;
    *width = 0; *height = 0; *timestamp100ns = 0;
    try {
        auto& c = *static_cast<Capture*>(handle);
        pump_capture_events();
        if (!c.valid() || IsIconic(c.hwnd)) return E_ACCESSDENIED;
        auto frame = c.pool.TryGetNextFrame();
        if (!frame) return S_FALSE;
        auto size = frame.ContentSize();
        int cw = size.Width, ch = size.Height;
        if (cw <= 0 || ch <= 0) return S_FALSE;
        if (c.max_in_w && (cw > c.max_in_w || ch > c.max_in_h)) {
            *width = cw; *height = ch;
            return HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED);
        }
        if (cw != c.width || ch != c.height) {
            if (!c.max_out_w) return HRESULT_FROM_WIN32(ERROR_RETRY);
            frame.Close();
            c.pool.Recreate(c.frame_device, DirectXPixelFormat::B8G8R8A8UIntNormalized, 2, size);
            c.width = cw; c.height = ch;
            return S_FALSE;  // 이전 크기 표면의 프레임은 버린다
        }
        if (!c.out_w) {
            if (c.max_out_w) fit_output(cw, ch, c.max_out_w, c.max_out_h, &c.out_w, &c.out_h);
            else { c.out_w = cw; c.out_h = ch; }
            if (c.want_nv12) {  // NV12(4:2:0)는 짝수 크기만 된다. 홀수 창은 GPU에서 1픽셀 줄여 맞춘다.
                c.out_w = c.out_w & ~1; c.out_h = c.out_h & ~1;
                if (c.out_w < 2) c.out_w = 2;
                if (c.out_h < 2) c.out_h = 2;
            }
        }
        const bool nv12 = c.want_nv12 && !c.nv12_failed;
        UINT64 bytes = nv12 ? UINT64(c.out_w) * UINT64(c.out_h) * 3 / 2 : UINT64(c.out_w) * UINT64(c.out_h) * 4;
        if (bytes > capacity) {
            // Report required geometry without writing any pixel data.
            *width = c.out_w; *height = c.out_h;
            return HRESULT_FROM_WIN32(ERROR_INSUFFICIENT_BUFFER);
        }
        auto access = frame.Surface().as<::Windows::Graphics::DirectX::Direct3D11::IDirect3DDxgiInterfaceAccess>();
        com_ptr<ID3D11Texture2D> texture;
        check_hresult(access->GetInterface(guid_of<ID3D11Texture2D>(), texture.put_void()));
        D3D11_TEXTURE2D_DESC desc{};
        texture->GetDesc(&desc);
        if (desc.Format != DXGI_FORMAT_B8G8R8A8_UNORM || desc.Width < UINT(cw) || desc.Height < UINT(ch))
            return E_UNEXPECTED;
        com_ptr<ID3D11Texture2D> staging;
        int format = BB_FORMAT_BGRA;
        if (nv12 && SUCCEEDED(scale_frame(c, texture.get(), cw, ch, BB_FORMAT_NV12))) {
            staging = c.scaler.staging;
            format = BB_FORMAT_NV12;
        } else if (nv12) {
            // GPU가 NV12 출력을 못 함: 이 캡처는 BGRA로 계속한다(ffmpeg가 CPU에서 변환, 이전 방식). 형식으로 알린다.
            c.nv12_failed = true;
            *width = c.out_w; *height = c.out_h;
            return S_FALSE;
        } else if (cw != c.out_w || ch != c.out_h) {
            // CPU 복사 전에 GPU에서 축소한다. 실패하면 CPU 축소로 대체하지 않는다.
            if (FAILED(scale_frame(c, texture.get(), cw, ch, BB_FORMAT_BGRA))) return BB_E_GPU_SCALE;
            staging = c.scaler.staging;
        } else {
            if (!c.copy_staging || c.copy_w != desc.Width || c.copy_h != desc.Height) {
                c.copy_staging = nullptr;
                desc.Usage = D3D11_USAGE_STAGING; desc.BindFlags = 0;
                desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ; desc.MiscFlags = 0;
                check_hresult(c.device->CreateTexture2D(&desc, nullptr, c.copy_staging.put()));
                c.copy_w = desc.Width; c.copy_h = desc.Height;
            }
            staging = c.copy_staging;
            c.context->CopyResource(staging.get(), texture.get());
        }
        D3D11_MAPPED_SUBRESOURCE mapped{};
        check_hresult(c.context->Map(staging.get(), 0, D3D11_MAP_READ, 0, &mapped));
        auto* source = static_cast<BYTE*>(mapped.pData);
        if (format == BB_FORMAT_NV12) {
            // Y 평면(out_h줄) 뒤에 UV 교차 평면(out_h/2줄)이 RowPitch*높이 위치에서 시작한다.
            for (int y = 0; y < c.out_h; ++y)
                std::memcpy(destination + UINT64(y) * c.out_w, source + UINT64(y) * mapped.RowPitch, UINT64(c.out_w));
            BYTE* uv = destination + UINT64(c.out_w) * c.out_h;
            const BYTE* uv_source = source + UINT64(mapped.RowPitch) * c.out_h;
            for (int y = 0; y < c.out_h / 2; ++y)
                std::memcpy(uv + UINT64(y) * c.out_w, uv_source + UINT64(y) * mapped.RowPitch, UINT64(c.out_w));
        } else {
            for (int y = 0; y < c.out_h; ++y)
                std::memcpy(destination + UINT64(y) * c.out_w * 4, source + UINT64(y) * mapped.RowPitch, UINT64(c.out_w) * 4);
        }
        c.context->Unmap(staging.get(), 0);
        pump_capture_events();
        // Recheck after copying; a late frame across Alt+Tab must be discarded.
        if (!c.valid() || IsIconic(c.hwnd)) return E_ACCESSDENIED;
        *width = c.out_w; *height = c.out_h; *timestamp100ns = frame.SystemRelativeTime().count();
        c.frame_format = format;
        return S_OK;
    } catch (...) { return to_hresult(); }
}
BB void __cdecl bb_close(void* handle) { delete static_cast<Capture*>(handle); }

// 블랙박스 11.4: 출력 형식 요청. 첫 프레임 전에만 바꿀 수 있다(출력 크기·형식은 녹화 중 고정).
BB HRESULT __cdecl bb_set_format(void* handle, int format) {
    if (!handle) return E_POINTER;
    if (format != BB_FORMAT_BGRA && format != BB_FORMAT_NV12) return E_INVALIDARG;
    auto& c = *static_cast<Capture*>(handle);
    if (c.out_w) return E_ILLEGAL_METHOD_CALL;
    c.want_nv12 = format == BB_FORMAT_NV12;
    return S_OK;
}

// 마지막으로 성공한 bb_read 프레임의 형식(BB_FORMAT_*). NV12를 요청했어도 GPU가 못 하면 BGRA다.
BB int __cdecl bb_frame_format(void* handle) {
    return handle ? static_cast<Capture*>(handle)->frame_format : BB_FORMAT_BGRA;
}
