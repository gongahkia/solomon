%{!?shisa_version:%global shisa_version 0.1.0}

Name: shisa
Version: %{shisa_version}
Release: 1%{?dist}
Summary: Daemon-backed async-first cross-shell prompt
License: MIT
URL: https://github.com/gongahkia/shisa
Source0: %{name}-%{version}.tar.gz

BuildRequires: zig
Requires: glibc

%description
Shisa keeps slow prompt work out of the shell by rendering through a
per-user daemon with cached prompt modules.

%prep
%autosetup

%build
zig build release --prefix "$PWD/zig-out/rpm"

%install
install -Dm755 zig-out/rpm/bin/shisa %{buildroot}%{_bindir}/shisa
install -Dm755 zig-out/rpm/bin/shisad %{buildroot}%{_bindir}/shisad
install -Dm755 zig-out/rpm/bin/shisa-supervisor %{buildroot}%{_bindir}/shisa-supervisor
install -Dm644 init/shisa.zsh %{buildroot}%{_datadir}/shisa/init/shisa.zsh
install -Dm644 init/shisa.bash %{buildroot}%{_datadir}/shisa/init/shisa.bash
install -Dm644 init/shisa.fish %{buildroot}%{_datadir}/shisa/init/shisa.fish
install -Dm644 init/shisa.nu %{buildroot}%{_datadir}/shisa/init/shisa.nu
install -Dm644 init/shisa.ps1 %{buildroot}%{_datadir}/shisa/init/shisa.ps1
install -d %{buildroot}%{_datadir}/shisa
cp -R themes %{buildroot}%{_datadir}/shisa/themes
cp -R examples %{buildroot}%{_datadir}/shisa/examples

%files
%license LICENSE
%doc README.md
%{_bindir}/shisa
%{_bindir}/shisad
%{_bindir}/shisa-supervisor
%{_datadir}/shisa

%changelog
* Wed Jun 17 2026 Shisa maintainers <angryapplegravy@gmail.com> - 0.1.0-1
- Initial package spec.
