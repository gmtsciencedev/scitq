#!/bin/sh

# Set default policies for all three default chains
iptables -P INPUT DROP
iptables -P FORWARD DROP
ip6tables -P INPUT DROP
ip6tables -P FORWARD DROP
iptables -P OUTPUT ACCEPT

# Enable free use of loopback interfaces
iptables -A INPUT -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT
ip6tables -A INPUT -i lo -j ACCEPT
ip6tables -A OUTPUT -o lo -j ACCEPT

# All TCP sessions should begin with SYN
iptables -A INPUT -p tcp ! --syn -m state --state NEW -s 0.0.0.0/0 -j DROP
ip6tables -A INPUT -p tcp ! --syn -m state --state NEW -s ::/0 -j DROP

# Accept inbound TCP packets
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
ip6tables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
#iptables -A INPUT -p tcp --dport 22 -m state --state NEW -s 0.0.0.0/0 -j ACCEPT

# Accept inbound packets from the trusted IPs
iptables -A INPUT -p all -s X.X.X.X/32 -j ACCEPT
iptables -A INPUT -p all -s Y.Y.Y.Y/32 -j ACCEPT
iptables -A INPUT -p all -s Z.Z.Z.Z/32 -j ACCEPT

