#version=RHEL9
eula --agreed
text
skipx
url --url=https://mirrors.huaweicloud.com/rockylinux/9/BaseOS/x86_64/os/
repo --name=AppStream --baseurl=https://mirrors.huaweicloud.com/rockylinux/9/AppStream/x86_64/os/

lang @@VBOX_INSERT_LOCALE@@
keyboard --xlayouts=us
timezone@@VBOX_COND_IS_RTC_USING_UTC@@ --utc@@VBOX_COND_END@@ @@VBOX_INSERT_TIME_ZONE_UX@@

network --bootproto=dhcp --device=link --activate --onboot=on --hostname=@@VBOX_INSERT_HOSTNAME_FQDN_SH@@
firewall --enabled --service=ssh
selinux --enforcing
services --enabled=sshd,chronyd

rootpw --lock
user --name=@@VBOX_INSERT_USER_LOGIN_SH@@ --groups=wheel --password=@@VBOX_INSERT_USER_PASSWORD_SH@@ --plaintext
sshkey --username=@@VBOX_INSERT_USER_LOGIN_SH@@ "@@ANSIBLE_SSH_PUBLIC_KEY@@"

bootloader --location=mbr --append="console=tty0"
zerombr
clearpart --all --initlabel
autopart --type=lvm

firstboot --disable
reboot --eject

%packages --ignoremissing
@core
chrony
openssh-server
python3
sudo
%end

%post --log=/root/ks-post.log
printf '%s\n' '@@VBOX_INSERT_USER_LOGIN@@ ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/90-ansible-bootstrap
chmod 0440 /etc/sudoers.d/90-ansible-bootstrap
systemctl enable sshd.service chronyd.service
%end
