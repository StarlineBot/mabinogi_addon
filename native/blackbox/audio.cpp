#include <climits>
// Process-tree loopback only. No default device, microphone or system-wide fallback.
#include <windows.h>
#include <audioclient.h>
#include <audioclientactivationparams.h>
#include <mmdeviceapi.h>
#include <wrl.h>
#include <memory>
#include <cstring>
using Microsoft::WRL::ComPtr;
#define BB extern "C" __declspec(dllexport)

extern bool capture_epoch_active(HWND hwnd);

struct Completion final : Microsoft::WRL::RuntimeClass<
    Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>,
    IActivateAudioInterfaceCompletionHandler, Microsoft::WRL::FtmBase> {
    HANDLE event = CreateEvent(nullptr, TRUE, FALSE, nullptr);
    HRESULT result = E_PENDING;
    ComPtr<IAudioClient> client;
    AUDIOCLIENT_ACTIVATION_PARAMS params{};
    ~Completion() { if (event) CloseHandle(event); }
    HRESULT STDMETHODCALLTYPE ActivateCompleted(IActivateAudioInterfaceAsyncOperation* operation) override {
        ComPtr<IUnknown> object;
        HRESULT activated = E_FAIL;
        result = operation->GetActivateResult(&activated, &object);
        if (SUCCEEDED(result)) result = activated;
        if (SUCCEEDED(result)) result = object.As(&client);
        SetEvent(event);
        return S_OK;
    }
};
struct Audio {
    HWND hwnd{}; DWORD pid{}; ULONGLONG created{}; HANDLE process{};
    ComPtr<IAudioClient> client;
    ComPtr<IAudioCaptureClient> capture;
    UINT block{}; bool seen = false;
    ~Audio() { if (client) client->Stop(); if (process) CloseHandle(process); }
    bool valid() {
        DWORD p{}; GetWindowThreadProcessId(hwnd, &p);
        FILETIME c{}, e{}, k{}, u{};
        return capture_epoch_active(hwnd) && p == pid && IsWindow(hwnd) && !IsIconic(hwnd) && GetForegroundWindow() == hwnd &&
            WaitForSingleObject(process, 0) == WAIT_TIMEOUT && GetProcessTimes(process, &c, &e, &k, &u) &&
            ((ULONGLONG(c.dwHighDateTime) << 32) | c.dwLowDateTime) == created;
    }
};
BB HRESULT __cdecl bb_audio_open(HWND hwnd, DWORD pid, ULONGLONG created, UINT rate,
                                UINT channels, DWORD timeout_ms, void** output) {
    if (!output || rate == 0 || channels == 0 || channels > 2 || timeout_ms == 0 || timeout_ms == INFINITE)
        return E_INVALIDARG;
    *output = nullptr;
    try {
        auto a = std::make_unique<Audio>();
        a->hwnd = hwnd; a->pid = pid; a->created = created;
        a->process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, pid);
        if (!a->process || !a->valid()) return E_ACCESSDENIED;
        auto completion = Microsoft::WRL::Make<Completion>();
        if (!completion || !completion->event) return E_OUTOFMEMORY;
        completion->params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
        completion->params.ProcessLoopbackParams.TargetProcessId = pid;
        completion->params.ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE;
        PROPVARIANT params{};
        params.vt = VT_BLOB;
        params.blob.cbSize = sizeof(completion->params);
        params.blob.pBlobData = reinterpret_cast<BYTE*>(&completion->params);
        ComPtr<IActivateAudioInterfaceAsyncOperation> operation;
        HRESULT hr = ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
            __uuidof(IAudioClient), &params, completion.Get(), &operation);
        if (FAILED(hr)) return hr;
        if (WaitForSingleObject(completion->event, timeout_ms) != WAIT_OBJECT_0)
            return HRESULT_FROM_WIN32(ERROR_TIMEOUT);
        if (FAILED(completion->result)) return completion->result;
        a->client = completion->client;
        WAVEFORMATEX format{};
        format.wFormatTag = WAVE_FORMAT_PCM; format.nChannels = WORD(channels);
        format.nSamplesPerSec = rate; format.wBitsPerSample = 16;
        format.nBlockAlign = WORD(channels * 2); format.nAvgBytesPerSec = rate * format.nBlockAlign;
        a->block = format.nBlockAlign;
        hr = a->client->Initialize(AUDCLNT_SHAREMODE_SHARED,
            AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM,
            0, 0, &format, nullptr);
        if (FAILED(hr)) return hr;
        hr = a->client->GetService(IID_PPV_ARGS(&a->capture));
        if (FAILED(hr)) return hr;
        if (!a->valid()) return E_ACCESSDENIED;
        hr = a->client->Start();
        if (FAILED(hr)) return hr;
        *output = a.release();
        return S_OK;
    } catch (...) { return E_FAIL; }
}
BB HRESULT __cdecl bb_audio_read(void* handle, BYTE* output, UINT capacity, UINT* bytes, UINT64* qpc100ns) {
    if (!handle || !output || !bytes || !qpc100ns) return E_POINTER;
    auto& a = *static_cast<Audio*>(handle);
    *bytes = 0; *qpc100ns = 0;
    if (!a.valid()) return E_ACCESSDENIED;
    UINT frames{};
    HRESULT hr = a.capture->GetNextPacketSize(&frames);
    if (FAILED(hr) || frames == 0) return FAILED(hr) ? hr : S_FALSE;
    UINT64 required = UINT64(frames) * a.block;
    if (required > capacity) {
        if (required <= UINT_MAX) *bytes = UINT(required);
        return HRESULT_FROM_WIN32(ERROR_INSUFFICIENT_BUFFER);
    }
    BYTE* data{}; DWORD flags{}; UINT64 position{};
    hr = a.capture->GetBuffer(&data, &frames, &flags, &position, qpc100ns);
    if (FAILED(hr)) return hr;
    // Check the authoritative packet size again before touching the destination.
    required = UINT64(frames) * a.block;
    if (required > capacity) {
        if (required <= UINT_MAX) *bytes = UINT(required);
        hr = a.capture->ReleaseBuffer(frames);
        return FAILED(hr) ? hr : HRESULT_FROM_WIN32(ERROR_INSUFFICIENT_BUFFER);
    }
    UINT count = UINT(required);
    if ((flags & AUDCLNT_BUFFERFLAGS_TIMESTAMP_ERROR) || (a.seen && (flags & AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY))) {
        a.capture->ReleaseBuffer(frames);
        return HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
    }
    if (flags & AUDCLNT_BUFFERFLAGS_SILENT) std::memset(output, 0, count);
    else std::memcpy(output, data, count);
    hr = a.capture->ReleaseBuffer(frames);
    if (FAILED(hr)) return hr;
    if (!a.valid()) return E_ACCESSDENIED;
    a.seen = true;
    *bytes = count;
    return S_OK;
}
BB void __cdecl bb_audio_close(void* handle) { delete static_cast<Audio*>(handle); }
