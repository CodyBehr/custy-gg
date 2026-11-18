// audiocap: records sound to a WAV file for custy coach's game recordings.
//
//   audiocap.exe <out.wav> <pid>   League's sound only (Windows 10 2004+ "process loopback": the game process and
//                                  anything it starts; Discord, music and notifications are left out)
//   audiocap.exe <out.wav> 0       everything the PC plays (fallback)
//
// Writes 48 kHz 16-bit stereo PCM. Silence is written for any stretch Windows sends nothing, so the file's length
// always matches the wall clock and lines up with the video. Prints "started <mode>" once capturing; stops when it
// reads "q" (or end of input) on stdin, then fixes up the WAV header and exits.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <audioclientactivationparams.h>
#include <wrl/implements.h>
#include <cstdio>
#include <cstdint>
#include <vector>
#include <atomic>
#include <thread>

#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "mmdevapi.lib")

using Microsoft::WRL::ClassicCom;
using Microsoft::WRL::FtmBase;
using Microsoft::WRL::RuntimeClass;
using Microsoft::WRL::RuntimeClassFlags;

static const DWORD RATE = 48000;
static const WORD CH = 2, BITS = 16, ALIGN = CH * BITS / 8;
static std::atomic<bool> g_stop{false};

class Completion : public RuntimeClass<RuntimeClassFlags<ClassicCom>, FtmBase, IActivateAudioInterfaceCompletionHandler> {
 public:
  HANDLE done = CreateEventW(nullptr, TRUE, FALSE, nullptr);
  HRESULT hr = E_FAIL;
  IAudioClient* client = nullptr;
  STDMETHOD(ActivateCompleted)(IActivateAudioInterfaceAsyncOperation* op) override {
    IUnknown* unk = nullptr;
    HRESULT hrAct = E_FAIL;
    hr = op->GetActivateResult(&hrAct, &unk);
    if (SUCCEEDED(hr)) hr = hrAct;
    if (SUCCEEDED(hr) && unk) hr = unk->QueryInterface(IID_PPV_ARGS(&client));
    if (unk) unk->Release();
    SetEvent(done);
    return S_OK;
  }
};

static WAVEFORMATEX fmt() {
  WAVEFORMATEX f = {};
  f.wFormatTag = WAVE_FORMAT_PCM;
  f.nChannels = CH;
  f.nSamplesPerSec = RATE;
  f.wBitsPerSample = BITS;
  f.nBlockAlign = ALIGN;
  f.nAvgBytesPerSec = RATE * ALIGN;
  return f;
}

static IAudioClient* process_client(DWORD pid) {
  AUDIOCLIENT_ACTIVATION_PARAMS ap = {};
  ap.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
  ap.ProcessLoopbackParams.TargetProcessId = pid;
  ap.ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE;
  PROPVARIANT pv = {};
  pv.vt = VT_BLOB;
  pv.blob.cbSize = sizeof(ap);
  pv.blob.pBlobData = reinterpret_cast<BYTE*>(&ap);
  auto handler = Microsoft::WRL::Make<Completion>();
  IActivateAudioInterfaceAsyncOperation* op = nullptr;
  HRESULT hr = ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, __uuidof(IAudioClient), &pv, handler.Get(), &op);
  if (FAILED(hr)) { fprintf(stderr, "activate failed 0x%08lx\n", hr); return nullptr; }
  WaitForSingleObject(handler->done, 5000);
  if (op) op->Release();
  if (FAILED(handler->hr) || !handler->client) { fprintf(stderr, "activate result 0x%08lx\n", handler->hr); return nullptr; }
  WAVEFORMATEX f = fmt();
  hr = handler->client->Initialize(AUDCLNT_SHAREMODE_SHARED,
                                   AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY,
                                   2000000, 0, &f, nullptr);
  if (FAILED(hr)) { fprintf(stderr, "process init failed 0x%08lx\n", hr); handler->client->Release(); return nullptr; }
  return handler->client;
}

static IAudioClient* system_client() {
  IMMDeviceEnumerator* en = nullptr;
  IMMDevice* dev = nullptr;
  IAudioClient* client = nullptr;
  if (FAILED(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, IID_PPV_ARGS(&en)))) return nullptr;
  HRESULT hr = en->GetDefaultAudioEndpoint(eRender, eConsole, &dev);
  en->Release();
  if (FAILED(hr)) { fprintf(stderr, "no output device 0x%08lx\n", hr); return nullptr; }
  hr = dev->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, reinterpret_cast<void**>(&client));
  dev->Release();
  if (FAILED(hr)) return nullptr;
  WAVEFORMATEX f = fmt();
  hr = client->Initialize(AUDCLNT_SHAREMODE_SHARED,
                          AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY,
                          2000000, 0, &f, nullptr);
  if (FAILED(hr)) { fprintf(stderr, "system init failed 0x%08lx\n", hr); client->Release(); return nullptr; }
  return client;
}

static void header(FILE* f, uint32_t data) {
  uint32_t riff = 36 + data, sixteen = 16, rate = RATE, bps = RATE * ALIGN;
  uint16_t pcm = 1, ch = CH, align = ALIGN, bits = BITS;
  fseek(f, 0, SEEK_SET);
  fwrite("RIFF", 1, 4, f); fwrite(&riff, 4, 1, f); fwrite("WAVEfmt ", 1, 8, f);
  fwrite(&sixteen, 4, 1, f); fwrite(&pcm, 2, 1, f); fwrite(&ch, 2, 1, f); fwrite(&rate, 4, 1, f);
  fwrite(&bps, 4, 1, f); fwrite(&align, 2, 1, f); fwrite(&bits, 2, 1, f);
  fwrite("data", 1, 4, f); fwrite(&data, 4, 1, f);
}

int wmain(int argc, wchar_t** argv) {
  if (argc < 3) { fprintf(stderr, "usage: audiocap <out.wav> <pid|0>\n"); return 2; }
  CoInitializeEx(nullptr, COINIT_MULTITHREADED);
  DWORD pid = static_cast<DWORD>(_wtoi(argv[2]));
  const char* mode = "game";
  IAudioClient* client = pid ? process_client(pid) : nullptr;
  if (!client) { mode = "system"; client = system_client(); }
  if (!client) { fprintf(stderr, "no audio capture available\n"); return 1; }
  IAudioCaptureClient* cap = nullptr;
  if (FAILED(client->GetService(IID_PPV_ARGS(&cap)))) { fprintf(stderr, "no capture service\n"); return 1; }

  FILE* out = _wfopen(argv[1], L"wb");
  if (!out) { fprintf(stderr, "can't write the file\n"); return 1; }
  header(out, 0);

  std::thread([] {   // "q" or end of input on stdin = stop
    int c;
    while ((c = getchar()) != EOF && c != 'q') {}
    g_stop = true;
  }).detach();

  LARGE_INTEGER freq, t0, now;
  QueryPerformanceFrequency(&freq);
  client->Start();
  QueryPerformanceCounter(&t0);
  printf("started %s\n", mode);
  fflush(stdout);

  uint64_t written = 0;   // frames
  std::vector<char> zeros(RATE / 10 * ALIGN, 0);
  while (!g_stop) {
    Sleep(10);
    UINT32 packet = 0;
    while (SUCCEEDED(cap->GetNextPacketSize(&packet)) && packet) {
      BYTE* data = nullptr; UINT32 frames = 0; DWORD flags = 0;
      if (FAILED(cap->GetBuffer(&data, &frames, &flags, nullptr, nullptr))) break;
      if (flags & AUDCLNT_BUFFERFLAGS_SILENT) {
        for (UINT32 left = frames; left;) { UINT32 n = left < RATE / 10 ? left : RATE / 10; fwrite(zeros.data(), ALIGN, n, out); left -= n; }
      } else {
        fwrite(data, ALIGN, frames, out);
      }
      written += frames;
      cap->ReleaseBuffer(frames);
    }
    // nothing playing: Windows sends nothing, so fill with silence to keep the file in step with the clock
    QueryPerformanceCounter(&now);
    uint64_t due = static_cast<uint64_t>((now.QuadPart - t0.QuadPart) * static_cast<double>(RATE) / freq.QuadPart);
    if (due > written + RATE / 5) {   // more than 200 ms behind
      uint64_t gap = due - written - RATE / 20;
      while (gap) { UINT32 n = gap < RATE / 10 ? static_cast<UINT32>(gap) : RATE / 10; fwrite(zeros.data(), ALIGN, n, out); gap -= n; written += n; }
    }
  }
  client->Stop();
  header(out, static_cast<uint32_t>(written * ALIGN));
  fclose(out);
  cap->Release();
  client->Release();
  CoUninitialize();
  return 0;
}
