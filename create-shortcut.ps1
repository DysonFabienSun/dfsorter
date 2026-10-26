$ErrorActionPreference = 'Stop'

$venvConfigPath = Join-Path $PSScriptRoot '.venv\pyvenv.cfg'
if (-not (Test-Path -LiteralPath $venvConfigPath)) {
    throw 'Python environment missing. Run uv sync --python 3.13 first.'
}

$pythonHome = Get-Content -LiteralPath $venvConfigPath |
    Where-Object { $_ -match '^home\s*=\s*(.+)$' } |
    ForEach-Object { $Matches[1].Trim() } |
    Select-Object -First 1
if (-not $pythonHome) {
    throw 'Python environment configuration has no home interpreter.'
}

$pythonwPath = Join-Path $pythonHome 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonwPath)) {
    throw "GUI Python interpreter missing at $pythonwPath."
}

$shortcutPath = Join-Path $PSScriptRoot 'DFSorter.lnk'
$shellObject = New-Object -ComObject WScript.Shell
$shortcut = $shellObject.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonwPath
$shortcut.Arguments = '"' + (Join-Path $PSScriptRoot 'launch.pyw') + '"'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = 'Open DFSorter without a console window'
$shortcut.IconLocation = (Join-Path $PSScriptRoot 'resources\mascot\dfsorter.ico') + ',0'
$shortcut.Save()

# WScript.Shell cannot write the AppUserModelID property. Use the Windows
# property store so the Python host and its shortcut share a taskbar identity.
if (-not ('DFSorter.ShortcutIdentity' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace DFSorter {
    public static class ShortcutIdentity {
        [StructLayout(LayoutKind.Sequential)]
        private struct PropertyKey {
            public Guid Format;
            public uint Id;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct PropVariant {
            public ushort Type, Reserved1, Reserved2, Reserved3;
            public IntPtr Value, Unused;
        }

        [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"),
         InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IPropertyStore {
            void GetCount(out uint count);
            void GetAt(uint index, out PropertyKey key);
            void GetValue(ref PropertyKey key, out PropVariant value);
            void SetValue(ref PropertyKey key, ref PropVariant value);
            void Commit();
        }

        [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
        private static extern void SHGetPropertyStoreFromParsingName(
            string path, IntPtr bindContext, uint flags, ref Guid iid,
            [MarshalAs(UnmanagedType.Interface)] out IPropertyStore store);

        public static void Set(string path, string appId) {
            Guid iid = typeof(IPropertyStore).GUID;
            IPropertyStore store;
            SHGetPropertyStoreFromParsingName(path, IntPtr.Zero, 2, ref iid, out store);
            var value = new PropVariant();
            try {
                var key = new PropertyKey {
                    Format = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), Id = 5
                };
                value.Type = 31; // VT_LPWSTR
                value.Value = Marshal.StringToCoTaskMemUni(appId);
                store.SetValue(ref key, ref value);
                store.Commit();
            } finally {
                Marshal.FreeCoTaskMem(value.Value);
                Marshal.ReleaseComObject(store);
            }
        }
    }
}
'@
}
[DFSorter.ShortcutIdentity]::Set($shortcutPath, 'DFSorter.Desktop')
Write-Output "Created $shortcutPath"
