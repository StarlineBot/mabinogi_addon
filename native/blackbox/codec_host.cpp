// Assign this helper to a kill-on-close job BEFORE starting the encoder.
// Parent termination closes the last job handle, including encoder descendants.
#include <windows.h>
int wmain() {
    const wchar_t* command = GetCommandLineW();
    if (*command == L'"') { ++command; while (*command && *command != L'"') ++command; if (*command) ++command; }
    else { while (*command && *command != L' ' && *command != L'\t') ++command; }
    while (*command == L' ' || *command == L'\t') ++command;
    if (!*command) return 125;
    HANDLE job = CreateJobObjectW(nullptr, nullptr);
    if (!job) return 125;
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION info{};
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, &info, sizeof(info)) ||
        !AssignProcessToJobObject(job, GetCurrentProcess())) { CloseHandle(job); return 125; }
    STARTUPINFOW start{}; start.cb = sizeof(start);
    start.dwFlags = STARTF_USESTDHANDLES;
    start.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    start.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    start.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    PROCESS_INFORMATION process{};
    // CreateProcess may modify its command buffer.
    const size_t count = lstrlenW(command) + 1;
    auto buffer = new wchar_t[count];
    lstrcpyW(buffer, command);
    BOOL created = CreateProcessW(nullptr, buffer, nullptr, nullptr, TRUE, CREATE_NO_WINDOW,
                                  nullptr, nullptr, &start, &process);
    delete[] buffer;
    if (!created) { CloseHandle(job); return 125; }
    CloseHandle(process.hThread);
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD result = 125;
    GetExitCodeProcess(process.hProcess, &result);
    CloseHandle(process.hProcess);
    // Closing job also terminates this member. Return value is emitted by ExitProcess;
    // kernel then closes the job, killing any leftover descendants.
    ExitProcess(result);
}
