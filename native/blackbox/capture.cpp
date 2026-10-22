// Original implementation using Windows SDK APIs. No desktop/monitor capture path.
// ABI calls for one handle must be serialized on its creating MTA worker thread.
#include <windows.h>
#include <d3d11.h>
#include <windows.graphics.capture.interop.h>
#include <windows.graphics.directx.direct3d11.interop.h>
#include <winrt/base.h>
#include <winrt/Windows.Graphics.Capture.h>
#include <winrt/Windows.Graphics.DirectX.h>
#include <winrt/Windows.Graphics.DirectX.Direct3D11.h>
#include <memory>
#include <cstring>
using namespace winrt;
using namespace winrt::Windows::Graphics::Capture;
using namespace winrt::Windows::Graphics::DirectX;
using namespace winrt::Windows::Graphics::DirectX::Direct3D11;
#define BB extern "C" __declspec(dllexport)

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
    int width{}, height{};
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

void CALLBACK foreground_event(HWINEVENTHOOK, DWORD, HWND hwnd, LONG, LONG, DWORD, DWORD) {
    if (active_capture && hwnd != active_capture->hwnd) active_capture->invalidated = true;
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

BB HRESULT __cdecl bb_open(HWND hwnd, DWORD pid, ULONGLONG created, int cursor, void** output) {
    if (!output) return E_POINTER;
    *output = nullptr;
    try {
        auto c = std::make_unique<Capture>();
        c->hwnd = hwnd; c->pid = pid; c->created = created;
        c->process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, pid);
        if (!c->process || !c->valid() || GetForegroundWindow() != hwnd || IsIconic(hwnd))
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
        c->pool = Direct3D11CaptureFramePool::CreateFreeThreaded(
            inspectable.as<IDirect3DDevice>(), DirectXPixelFormat::B8G8R8A8UIntNormalized, 2, size);
        c->session = c->pool.CreateCaptureSession(item);
        // Unsupported cursor control fails; do not silently adopt a different policy.
        c->session.IsCursorCaptureEnabled(cursor != 0);
        if (active_capture) return E_UNEXPECTED;
        active_capture = c.get();
        c->hook = SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, nullptr,
                                 foreground_event, 0, 0, WINEVENT_OUTOFCONTEXT);
        if (!c->hook) return HRESULT_FROM_WIN32(GetLastError());
        c->session.StartCapture();
        *output = c.release();
        return S_OK;
    } catch (...) { return to_hresult(); }
}

// S_FALSE: no frame. E_ACCESSDENIED: foreground/identity changed; caller closes and recreates.
// Resize requires a fresh segment/format; never silently scale or mix frames.
BB HRESULT __cdecl bb_read(void* handle, BYTE* destination, UINT64 capacity,
                          int* width, int* height, INT64* timestamp100ns) {
    if (!handle || !destination || !width || !height || !timestamp100ns) return E_POINTER;
    try {
        auto& c = *static_cast<Capture*>(handle);
        pump_capture_events();
        if (!c.valid() || GetForegroundWindow() != c.hwnd || IsIconic(c.hwnd)) return E_ACCESSDENIED;
        auto frame = c.pool.TryGetNextFrame();
        if (!frame) return S_FALSE;
        auto size = frame.ContentSize();
        if (size.Width != c.width || size.Height != c.height) return HRESULT_FROM_WIN32(ERROR_RETRY);
        UINT64 bytes = UINT64(c.width) * UINT64(c.height) * 4;
        if (bytes > capacity) return HRESULT_FROM_WIN32(ERROR_INSUFFICIENT_BUFFER);
        auto access = frame.Surface().as<::Windows::Graphics::DirectX::Direct3D11::IDirect3DDxgiInterfaceAccess>();
        com_ptr<ID3D11Texture2D> texture;
        check_hresult(access->GetInterface(guid_of<ID3D11Texture2D>(), texture.put_void()));
        D3D11_TEXTURE2D_DESC desc{};
        texture->GetDesc(&desc);
        if (desc.Format != DXGI_FORMAT_B8G8R8A8_UNORM || desc.Width < UINT(c.width) || desc.Height < UINT(c.height))
            return E_UNEXPECTED;
        desc.Usage = D3D11_USAGE_STAGING; desc.BindFlags = 0;
        desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ; desc.MiscFlags = 0;
        com_ptr<ID3D11Texture2D> staging;
        check_hresult(c.device->CreateTexture2D(&desc, nullptr, staging.put()));
        c.context->CopyResource(staging.get(), texture.get());
        D3D11_MAPPED_SUBRESOURCE mapped{};
        check_hresult(c.context->Map(staging.get(), 0, D3D11_MAP_READ, 0, &mapped));
        for (int y = 0; y < c.height; ++y)
            std::memcpy(destination + UINT64(y) * c.width * 4,
                        static_cast<BYTE*>(mapped.pData) + UINT64(y) * mapped.RowPitch, c.width * 4);
        c.context->Unmap(staging.get(), 0);
        pump_capture_events();
        // Recheck after copying; a late frame across Alt+Tab must be discarded.
        if (!c.valid() || GetForegroundWindow() != c.hwnd || IsIconic(c.hwnd)) return E_ACCESSDENIED;
        *width = c.width; *height = c.height; *timestamp100ns = frame.SystemRelativeTime().count();
        return S_OK;
    } catch (...) { return to_hresult(); }
}
BB void __cdecl bb_close(void* handle) { delete static_cast<Capture*>(handle); }
