/* MatreshkaViewer.exe (and MatreshkaKinetic.exe, built with /DKINETIC_DOOR):
 * the door, in C, so that it starts in milliseconds.
 *
 * The file is laid out by binpack.py as
 *
 *     [this door] [the installer: launcher.py, one file] [zip of the program]
 *
 * and the zip's comment, at the very end of the file, says
 *
 *     MTRBIN1;id=<build>;installer=<offset>,<length>;
 *
 * Every start reads that line. If bin\<build> beside the door is laid out
 * (it holds .complete), the program is started from there with the same
 * arguments, MATRESHKA_HOME telling it where it lives, and the door is done.
 * Otherwise the installer is written out as bin\install-<build>.exe and
 * started with --from <this file>: it lays the build out -- showing how far
 * it has got -- and starts the program itself. See launcher.py.
 *
 * MatreshkaKinetic.exe is only the first half: it starts the
 * MatreshkaViewer.exe beside it with --kinetic, as kin_launcher.py did.
 */
#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>

#define TITLE L"Matreshka Viewer"
#define BIG 32768

static void fail(const wchar_t *text)
{
    MessageBoxW(NULL, text, TITLE, MB_ICONERROR);
}

/* What follows the program's own name on the command line, as it was typed. */
static const wchar_t *rest_of_command_line(void)
{
    const wchar_t *line = GetCommandLineW();
    if (*line == L'"') {
        line++;
        while (*line && *line != L'"')
            line++;
        if (*line == L'"')
            line++;
    } else {
        while (*line && *line != L' ' && *line != L'\t')
            line++;
    }
    while (*line == L' ' || *line == L'\t')
        line++;
    return line;
}

static int start(const wchar_t *program, const wchar_t *before, const wchar_t *folder)
{
    static wchar_t command[BIG];
    STARTUPINFOW info;
    PROCESS_INFORMATION process;
    const wchar_t *rest = rest_of_command_line();
    _snwprintf(command, BIG - 1, L"\"%ls\"%ls%ls%ls%ls", program,
               before[0] ? L" " : L"", before, rest[0] ? L" " : L"", rest);
    command[BIG - 1] = 0;
    ZeroMemory(&info, sizeof(info));
    info.cb = sizeof(info);
    ZeroMemory(&process, sizeof(process));
    if (!CreateProcessW(program, command, NULL, NULL, FALSE, 0, NULL, folder,
                        &info, &process)) {
        static wchar_t said[BIG];
        _snwprintf(said, BIG - 1, L"Could not start %ls (error %lu).\n"
                   L"Не получилось запустить %ls (ошибка %lu).",
                   program, GetLastError(), program, GetLastError());
        said[BIG - 1] = 0;
        fail(said);
        return 1;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR line, int show)
{
    static wchar_t self[MAX_PATH * 4], folder[MAX_PATH * 4], target[MAX_PATH * 4];
    wchar_t *slash;
    (void)instance; (void)previous; (void)line; (void)show;

    if (!GetModuleFileNameW(NULL, self, MAX_PATH * 4))
        return 1;
    wcscpy(folder, self);
    slash = wcsrchr(folder, L'\\');
    if (slash)
        *slash = 0;

#ifdef KINETIC_DOOR
    _snwprintf(target, MAX_PATH * 4 - 1, L"%ls\\MatreshkaViewer.exe", folder);
    if (GetFileAttributesW(target) == INVALID_FILE_ATTRIBUTES) {
        fail(L"MatreshkaViewer.exe is not beside MatreshkaKinetic.exe.\n"
             L"MatreshkaViewer.exe не найден рядом с MatreshkaKinetic.exe.");
        return 1;
    }
    return start(target, L"--kinetic", folder);
#else
    {
        HANDLE file;
        LARGE_INTEGER size, at;
        static char tail[8192 + 1];
        DWORD got = 0, want;
        char *mark, *id_at, *id_end, *inst_at;
        static wchar_t id[256], complete[MAX_PATH * 4], installer[MAX_PATH * 4], before[MAX_PATH * 5];
        unsigned long long offset = 0, length = 0;
        int n;

        file = CreateFileW(self, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE, NULL,
                           OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
        if (file == INVALID_HANDLE_VALUE || !GetFileSizeEx(file, &size)) {
            fail(L"The door cannot read itself.\nДверь не может прочитать сама себя.");
            return 1;
        }
        want = (DWORD)(size.QuadPart < 8192 ? size.QuadPart : 8192);
        at.QuadPart = size.QuadPart - want;
        SetFilePointerEx(file, at, NULL, FILE_BEGIN);
        ReadFile(file, tail, want, &got, NULL);
        tail[got] = 0;
        /* The marker is text at the end of a binary tail: look for it by hand. */
        mark = NULL;
        for (n = (int)got - 8; n >= 0; n--) {
            if (memcmp(tail + n, "MTRBIN1;", 8) == 0) {
                mark = tail + n;
                break;
            }
        }
        id_at = mark ? strstr(mark, "id=") : NULL;
        inst_at = mark ? strstr(mark, "installer=") : NULL;
        if (!id_at || !inst_at) {
            CloseHandle(file);
            fail(L"There is no program packed in this door.\nВ этой двери нет программы.");
            return 1;
        }
        id_at += 3;
        id_end = strchr(id_at, ';');
        if (!id_end || id_end - id_at >= 255) {
            CloseHandle(file);
            return 1;
        }
        MultiByteToWideChar(CP_UTF8, 0, id_at, (int)(id_end - id_at), id, 255);
        id[id_end - id_at] = 0;
        sscanf(inst_at + 10, "%llu,%llu", &offset, &length);

        _snwprintf(complete, MAX_PATH * 4 - 1, L"%ls\\bin\\%ls\\.complete", folder, id);
        _snwprintf(target, MAX_PATH * 4 - 1, L"%ls\\bin\\%ls\\MatreshkaViewer.exe", folder, id);
        SetEnvironmentVariableW(L"MATRESHKA_HOME", folder);
        if (GetFileAttributesW(complete) != INVALID_FILE_ATTRIBUTES) {
            CloseHandle(file);
            return start(target, L"", folder);
        }

        /* Not laid out yet: the installer does it. */
        _snwprintf(installer, MAX_PATH * 4 - 1, L"%ls\\bin", folder);
        CreateDirectoryW(installer, NULL);
        _snwprintf(installer, MAX_PATH * 4 - 1, L"%ls\\bin\\install-%ls.exe", folder, id);
        if (GetFileAttributesW(installer) == INVALID_FILE_ATTRIBUTES) {
            HANDLE out;
            static char block[1 << 20];
            unsigned long long left = length;
            wchar_t part[MAX_PATH * 4];
            _snwprintf(part, MAX_PATH * 4 - 1, L"%ls.part", installer);
            out = CreateFileW(part, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL, NULL);
            if (out == INVALID_HANDLE_VALUE) {
                CloseHandle(file);
                fail(L"Cannot write into the bin folder beside the program.\n"
                     L"Не получается писать в папку bin рядом с программой.");
                return 1;
            }
            at.QuadPart = (LONGLONG)offset;
            SetFilePointerEx(file, at, NULL, FILE_BEGIN);
            while (left > 0) {
                DWORD chunk = (DWORD)(left < sizeof(block) ? left : sizeof(block));
                DWORD read = 0, written = 0;
                if (!ReadFile(file, block, chunk, &read, NULL) || read == 0)
                    break;
                WriteFile(out, block, read, &written, NULL);
                left -= read;
            }
            CloseHandle(out);
            if (left != 0 || !MoveFileExW(part, installer, MOVEFILE_REPLACE_EXISTING)) {
                CloseHandle(file);
                DeleteFileW(part);
                fail(L"Could not unpack the installer.\nНе получилось распаковать установщик.");
                return 1;
            }
        }
        CloseHandle(file);
        _snwprintf(before, MAX_PATH * 5 - 1, L"--from \"%ls\"", self);
        return start(installer, before, folder);
    }
#endif
}
