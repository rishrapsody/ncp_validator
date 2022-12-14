import os
from netmiko import ConnectHandler
import jc
import user_data
import argparse
import csv
import requests
import json
import git
from pprint import pprint
from texttable import Texttable
from datetime import datetime
from colorama import init, Fore, Back, Style
from typing import List,Dict,Union
import ipaddress
import re
import urllib3
from ipaddress import ip_address
from server_mapping import server_mapping
urllib3.disable_warnings()

## script help content
parser = argparse.ArgumentParser(description='''
You can provide input in below format:
Valid:
1. Enter PrivateAccess nxID(separated by commas)[eg.4042106,3150376] :->> 3150376
2. Enter PrivateAccess nxID(separated by commas)[eg.4042106,3150376] :->> 3150376,4042106

Invalid:
1. Enter PrivateAccess nxID(separated by commas)[eg.4042106,3150376] :->> 3150376, ABC
2. Enter PrivateAccess nxID(separated by commas)[eg.4042106,3150376] :->> 3150376XYZ

Default path for Proxy file: ~/.ssh/config (update ssh_config_file variable if its different for you)
''',formatter_class=argparse.RawTextHelpFormatter)

args = parser.parse_args()



## function to get user input and save as a list
def get_user_input() -> List:
    try:
        user_input = input("Enter PrivateAccess nxID(separated by commas)[eg.4042106,3150376] :->> ")
        input_parsed = [int(x.strip()) for x in user_input.split(',')]
        return(input_parsed)

    except ValueError as e:
        print(e)
        exit("Invalid user inputs. Please try again")
    #    get_user_input()
    except Exception as e:
        print(e)
        exit("Re-check input")
     #   get_user_input()

## function to get arvpnID, custcode, custid, localsubnet for each nexus in input list
def find_arvpnID_mapping(input: List) -> Union[Dict,Dict,Dict,Dict,Dict]:
    try:
        headers = {'Content-Type': 'application/json'}
        arvpn = {}
        cust_code = {}
        cust_id = {}
        local_subnet = {}
        site_name = {}
        pop_edge_ip = {}
        for nx_id in input:
            url = "{}/eagleeye/api/nexus/{}/info?nexus_id".format(user_data.ee_url,nx_id)
            response = requests.request("GET", url, headers=headers,verify=False,timeout=5).json()
            pop_edge_ip[nx_id] =  response["pop_edge_ip"]
            temp = []
            if len(response["routeInfo"]["route"]["localSubnets"]) == 0:
                local_subnet[nx_id] = Fore.RED+"None"+Fore.RESET
            elif len(response["routeInfo"]["route"]["localSubnets"]) == 1:
                subnet = response["routeInfo"]["route"]["localSubnets"][0]["ip"] + "/" + response["routeInfo"]["route"]["localSubnets"][0]["mask"]
                temp.append(subnet)
                local_subnet[nx_id] = temp
            else:
                
                for i in range(len(response["routeInfo"]["route"]["localSubnets"])):
                    subnet = response["routeInfo"]["route"]["localSubnets"][i]["ip"] + "/" + response["routeInfo"]["route"]["localSubnets"][i]["mask"]
                    temp.append(subnet)
                local_subnet[nx_id] = temp
            if response.get('arvpn_machine_id') !=  None and response['arvpn_machine_id'] != 0:
                arvpn[nx_id] = response["arvpn_machine_id"]
            else:
                print("Unable to find arvpn server from API response. Switching to backup static mapping....")
                #print(server_mapping[response["cust_ip"]])
                arvpn[nx_id] = server_mapping[response["cust_ip"]] + "." + response["pop_code"].lower()
                #print(arvpn[nx_id])


            #else:
            #    errors_list.append("Unable to find arvpn server-id. Check if nexus {} is of type PrivateAccess. Nexus may be using older edge provider".format(nx_id))
            #    exit("\nUnable to find arvpn server-id. \n->Check if nexus {} is of type PrivateAccess. \n->Nexus may be using older edge provider \n->Nexus is either not active or has no connexus \n->EE API is not returning ARVPN Machine ID. Please re-try after sometime".format(nx_id))
            cust_code[nx_id] = response["customer_code"].lower()
            cust_id[nx_id] = response["customer_id"]
            site_name[nx_id] =  response["loc_name"]
        return(arvpn,cust_code,cust_id,local_subnet,site_name,pop_edge_ip)
    except requests.exceptions.ConnectionError as e:
        errors_list.append("Either EE is unresponsive or your VPN is Down. Please check")
        func = "find_arvpnID_mapping"
        report_admin(func,e,errors_list)
        exit("\nUnable to establish connection with EE API server. Check if your VPN is UP and EE is accessible.\nInform Admin if the problem persists for longer time.")
    except requests.exceptions.Timeout as e:
        print ("Timeout Error:",e) 
    except ConnectionRefusedError as e:
        errors_list.append("Either EE is unresponsive or your VPN is Down. Please check")
        func = "find_arvpnID_mapping"
        report_admin(func,e,errors_list)
        exit("\nUnable to establish connection with EE API server. Check if your VPN is UP and EE is accessible.\nInform Admin if the problem persists for longer time.")
    except Exception as e:
        print(e)
        errors_list.append("Either EE is unresponsive or nexus is not PrivateAccess. Please check")
        func = "find_arvpnID_mapping"
        report_admin(func,e,errors_list)
        #exit("Landed into exception while executing EE Nexus API.\n->Unable to find arvpn server for input nx: {}\n->EE API might be unresponsive. Check with Admin".format(nx_id))
        exit("\nUnable to find arvpn server-id. \n->Check if nexus {} is of type PrivateAccess. \n->Nexus may be using older edge provider \n->Nexus is either not active or has no connexus \n->EE API is not returning ARVPN Machine ID. Please re-try after sometime".format(nx_id))


## function to get arvpn server hostname for each arvpnID. Returns nexus to server hostname mapping
def find_arvpn_server(arvpn_dict: Dict) -> Dict:
    try:
        temp_dict = {}
        for k,v in arvpn_dict.items():
            if not str(v).startswith("server"):
                headers = {'Content-Type': 'application/json'}
                url = "{}/eagleeye/command/run".format(user_data.ee_url)
                payload = json.dumps({"commandName":"uname -a","entityType":"mach","entityId":[v],"roles":["arvpn"],"blocking":"true"})
                response = requests.request("GET", url, headers=headers, data=payload,verify=False,timeout=5).json()
                temp_dict[k] = response["batch"]["exec"][0]["hostName"]
            else:
                temp_dict[k] = v
        return(temp_dict)
    except requests.exceptions.ConnectionError:
        exit("Unable to establish connection with API server. Check if your VPN is UP\n")
    except requests.exceptions.Timeout as e:
        print ("Timeout Error:",e) 
    except Exception as e:
        print(e)
        errors_list.append("Unable to parse arvpn server name using API call. Check with Admin")
        func = "find_arvpn_server"
        report_admin(func,e,errors_list)
        exit("Landed into exception while executing EE Command API.\n->Unable to find arvpn hostname for nx: {}\n->EE API might be unresponsive. Check with Admin".format(k))


## function to get vpn tunnel status and return dictionary per nexus
def get_vpn_tunnel_status(input: List,cust_id: Dict) -> Dict:
    try:
        tunnel_info = {}
        headers = {'Content-Type': 'application/json'}
        for nx_id in input:
            url = "{}/eagleeye/api/customer/{}/nexus/down".format(user_data.ee_url,cust_id[nx_id])
            response = requests.request("GET", url, headers=headers,verify=False,timeout=5).json()
            if nx_id in response["nexusIds"]:
                tunnel_info[nx_id] = Fore.RED+"DOWN"+Fore.RESET
            else:
                tunnel_info[nx_id] = "UP"
        return(tunnel_info)
    except requests.exceptions.ConnectionError:
        exit("Unable to establish connection with API server. Check if your VPN is UP\n")
    except requests.exceptions.Timeout as e:
        print ("Timeout Error:",e) 
    except Exception as e:
        #print(e)
        func ="get_vpn_tunnel_status"
        err_list = "Landed into exception while executing EE Tunnel Status API.\n->Unable to find TunnelStatus for nx: {}".format(nx_id)
        report_admin(func,e,err_list)
        exit("Landed into exception while executing EE Tunnel Status API.\n->Unable to find TunnelStatus for nx: {}\n->EE API might be unresponsive. Check with Admin".format(nx_id))


## function to parse link profiles and validate config
def validate_link_profile(profiles: Dict,nexus: str,pop: str,cust_code: Dict,tunnel_info: Dict,pop_edge_ip: Dict) -> List:
    #pprint(profiles)
    lp_data = []
    #print(nexus)
    for lp in profiles:
        if not str(nexus) in lp["Name"]:
            pass
        else:
            #pprint(lp)
            try:
                exp_name = "{}-{}-{}".format(cust_code[nexus],pop,nexus)
                if not exp_name == lp["Name"]:
                    lp_data.append(["LinkProfile","Name",lp["Name"],"custcode-pop-nexus",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    lp_data.append(["LinkProfile", "Name", lp["Name"], "custcode-pop-nexus", "PASSED"])
            except Exception as e:
                lp_data.append(["LinkProfile","Name","NA","custcode-pop-nexus",Fore.RED+"FAILED"+Fore.RESET])
            try:
                if lp["Direction"] != 'bidirectional':
                    lp_data.append(["LinkProfile","Direction",lp['Direction'],"bidirectional",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    lp_data.append(["LinkProfile", "Direction", lp['Direction'], "bidirectional", "PASSED"])
            except Exception as e:
                lp_data.append(["LinkProfile", "Direction", "Not Configured", "bidirectional", Fore.RED+"FAILED"+Fore.RESET])

            try:
                if "State" in lp.keys():
                    if lp["State"] != 'enabled':
                        lp_data.append(["LinkProfile","State",lp["State"],"Enabled at Secure-Server level",Fore.RED+"FAILED"+Fore.RESET])
                    else:
                        lp_data.append(["LinkProfile","State",lp["State"],"Enabled at Secure-Server level","PASSED"])
                else:
                    if tunnel_info[nexus] == "UP":
                        lp_data.append(["LinkProfile","State","enabled","enabled","PASSED"])
                    else:
                        lp_data.append(["LinkProfile","State","Unable to find key","enabled",Fore.MAGENTA+"N/A"+Fore.RESET])
            except Exception as e:
                #print(e)
                lp_data.append(["LinkProfile","State","Unable to find key","enabled",Fore.RED+"FAILED"+Fore.RESET])

            try:
                if int(lp["Timeout"]) != int(0):
                    lp_data.append(["LinkProfile","Timeout",lp["Timeout"],"0",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    lp_data.append(["LinkProfile", "Timeout", lp["Timeout"], "0", "PASSED"])
            except Exception as e:
                lp_data.append(["LinkProfile", "Timeout", "Not Configured", "0", Fore.RED+"FAILED"+Fore.RESET])

            try:
                if ip_address(pop_edge_ip[nexus]).is_private != True:
                    lp_data.append(["LinkProfile","RemoteUserId/VpnEndpoint",lp["RemoteUserId"],"RemoteUserId=VpnEndpoint=Pri_PopEdgeIP",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    if lp["RemoteUserId"] != lp["VpnTunnelEndpoint"] or lp["RemoteUserId"] != pop_edge_ip[nexus] or lp["VpnTunnelEndpoint"] != pop_edge_ip[nexus]:
                        lp_data.append(["LinkProfile","RemoteUserId/VpnEndpoint",lp["RemoteUserId"],"RemoteUserId=VpnEndpoint={}".format(pop_edge_ip[nexus]),Fore.RED+"FAILED"+Fore.RESET])
                    else:
                        lp_data.append(["LinkProfile", "RemoteUserId/VpnEndpoint", lp["RemoteUserId"],
                                    "RemoteUserId=VpnEndpoint=PopEdgeIP", "PASSED"])
            except Exception as e:
                lp_data.append(["LinkProfile","RemoteUserId/VpnEndpoint","Not Configured","RemoteUserId=VpnEndpoint={}".format(pop_edge_ip[nexus]),Fore.RED+"FAILED"+Fore.RESET])

            # try:
            #     if "asn" not in lp["IkePolicy"]:
            #         lp_data.append(["LinkProfile","IkePolicy",lp["IkePolicy"],"ike-policy-asn-default",Fore.RED+"FAILED"+Fore.RESET])
            #     else:
            #         lp_data.append(["LinkProfile", "IkePolicy", lp["IkePolicy"], "ike-policy-asn-default", "PASSED"])
            # except Exception as e:
            #     lp_data.append(["LinkProfile","IkePolicy","Not Set or Configured at Template","ike-policy-asn-default",Fore.RED+"FAILED"+Fore.RESET])

            # try:
            #     if "asn" not in lp["IPSecPolicy"]:
            #         lp_data.append(["LinkProfile","IPSecPolicy",lp["IPSecPolicy"],"ipsec-policy-asn-default",Fore.RED+"FAILED"+Fore.RESET])
            #     else:
            #         lp_data.append(["LinkProfile", "IPSecPolicy", lp["IPSecPolicy"], "ipsec-policy-asn-default", "PASSED"])
            # except Exception as e:
            #     lp_data.append(["LinkProfile","IPSecPolicy","Not Set or Configured at Template","ipsec-policy-asn-default",Fore.RED+"FAILED"+Fore.RESET])

            #ike-policy
            try:
                if "IkeV2Policy" not in lp.keys():
                    lp_data.append(["LinkProfile","IkeV2Policy","Not Configured","ikev2-policy",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    if "ikev2-policy" in lp["IkeV2Policy"]:
                        lp_data.append(["LinkProfile", "IkeV2Policy", lp["IkeV2Policy"], "ikev2-policy", "PASSED"])
                    else:
                        lp_data.append(["LinkProfile","IkeV2Policy",lp["IkeV2Policy"],"ikev2-policy",Fore.RED+"FAILED"+Fore.RESET])
            except Exception as e:
                lp_data.append(["LinkProfile","IkeV2Policy","Unable to find","ikev2-policy",Fore.RED+"FAILED"+Fore.RESET])

            try:
                if lp["PrivateIpAddress"] != "255.255.255.255":
                    lp_data.append(["LinkProfile","PrivateIpAddress",lp["PrivateIpAddress"],"255.255.255.255",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    lp_data.append(["LinkProfile", "PrivateIpAddress", lp["PrivateIpAddress"], "255.255.255.255", "PASSED"])

            except Exception as e:
                lp_data.append(["LinkProfile","PrivateIpAddress","Not Configured","255.255.255.255",Fore.RED+"FAILED"+Fore.RESET])

            # try:
            #     if lp["ExchangeMode"] != "main":
            #         lp_data.append(["LinkProfile","ExchangeMode",lp["ExchangeMode"],"main",Fore.RED+"FAILED"+Fore.RESET])
            #     else:
            #         lp_data.append(["LinkProfile", "ExchangeMode", lp["ExchangeMode"], "main", "PASSED"])
            # except Exception as e:
            #     lp_data.append(["LinkProfile","ExchangeMode","Not Configured","main",Fore.RED+"FAILED"+Fore.RESET])

            #ikev2
            try:
                if lp["ExchangeMode"] != "IKEv2":
                    lp_data.append(["LinkProfile","ExchangeMode",lp["ExchangeMode"],"IKEv2",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    lp_data.append(["LinkProfile", "ExchangeMode", lp["ExchangeMode"], "IKEv2", "PASSED"])
            except Exception as e:
                lp_data.append(["LinkProfile","ExchangeMode","Not Configured","IKEv2",Fore.RED+"FAILED"+Fore.RESET])

            try:
                if "IkeV2Auth" not in lp.keys():
                    lp_data.append(["LinkProfile","IkeV2Auth","Not Configured","PSK",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    if lp["IkeV2Auth"] == "PSK":
                        lp_data.append(["LinkProfile", "IkeV2Auth", lp["IkeV2Auth"], "PSK", "PASSED"])
                    else:
                        lp_data.append(["LinkProfile","IkeV2Auth",lp["IkeV2Auth"],"PSK",Fore.RED+"FAILED"+Fore.RESET])
            except Exception as e:
                lp_data.append(["LinkProfile","IkeV2Auth","Not Configured","PSK",Fore.RED+"FAILED"+Fore.RESET])

    return(lp_data)

## function to parse domain groups and validate config
def validate_domain_group(groups: Dict,nexus: str,pop: str,cust_code: Dict,tunnel_info: Dict,local_subnet: Dict,cust_id: Dict) -> List:
    dg_data = []
    for dg in groups:
        if not cust_code[nexus] in dg["Name"]:
            pass
        else:
            #pprint(dg)
            # try:
            #     if not dg["Name"].startswith(cust_code[nexus]) and not dg["Name"].endswith("row") or not dg["Name"].startswith(cust_code[nexus]) and not dg["Name"].endswith("mlc"):
            #         dg_data.append(["DomainGroup","Name",dg["Name"],"Start with custcode and end with region",Fore.RED+"FAILED"+Fore.RESET])
            #     else:
            #         dg_data.append(["DomainGroup", "Name", dg["Name"], "Start with custcode and end with region", "PASSED"])
            # except Exception as e:
            #     dg_data.append(["DomainGroup", "Name", "Not Configured", "Start with custcode and end with region", Fore.RED+"FAILED"+Fore.RESET])

            
            try:
                name = re.search(r"^([a-z]+)-([0-9]{1,4})-([a-z]+)-([a-z]+)-([0-9]{1,2})-([a-z]+)$",dg["Name"])
                if name.group(1) == cust_code[nexus] and int(name.group(2)) == cust_id[nexus] and name.group(3) == "domain" and name.group(4) == "group" and int(name.group(5)) in range(1,99): 
                    if name.group(6) == "mlc" or name.group(6) == "row":
                        dg_data.append(["DomainGroup", "Name", dg["Name"], "custcode-custid-domain-group-xx-mlc|row", "PASSED"])
                    else:
                       dg_data.append(["DomainGroup","Name",dg["Name"],"custcode-custid-domain-group-xx-mlc|row",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    dg_data.append(["DomainGroup","Name",dg["Name"],"custcode-custid-domain-group-xx-mlc|row",Fore.RED+"FAILED"+Fore.RESET])
            except Exception as e:
                dg_data.append(["DomainGroup", "Name", dg["Name"], "custcode-custid-domain-group-xx-mlc|row", Fore.RED+"FAILED"+Fore.RESET])


            try:
                if "State" in dg.keys():
                    if dg["State"] != "enabled":
                        dg_data.append(["DomainGroup", "State", dg["State"], "Enabled at Secure-Server level", Fore.RED+"FAILED"+Fore.RESET])
                    else:
                        dg_data.append(["DomainGroup", "State", dg["State"], "Enabled at Secure-Server level", "PASSED"])
                else:
                    dg_data.append(["DomainGroup", "State", "enabled", "enabled", "PASSED"])
            except Exception as e:
                #print(e)
                dg_data.append(["DomainGroup", "State", "Unable to find key", "enabled", Fore.RED+"FAILED"+Fore.RESET])

            try:
                if dg['Suffix'] == "" or '.' not in dg['Suffix']:
                    dg_data.append(["DomainGroup","Suffix",dg['Suffix'],"Should not be empty",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    dg_data.append(["DomainGroup", "Suffix", dg['Suffix'], "Should not be empty", "PASSED"])
            except Exception as e:
                dg_data.append(["DomainGroup","Suffix","Not Configured","Should not be empty",Fore.RED+"FAILED"+Fore.RESET])

            try:
                if "DomainSearchOrder" in dg.keys():
                    dg_data.append(["DomainGroup", "DSSO", dg["DomainSearchOrder"], "NA","NA"])
            except Exception as e:
                dg_data.append(["DomainGroup", "DSSO", "Unable to Parse", "NA",Fore.RED + "FAILED" + Fore.RESET])


            try:
                if dg["DNS1"] == "" and dg["DNS2"] == "":
                    dg_data.append(["DomainGroup","DNS","","Atleast one should be configured",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    dg_data.append(["DomainGroup", "DNS", dg["DNS1"] + "/" + dg["DNS2"] , "Atleast one should be configured", "PASSED"])
            except Exception as e:
                dg_data.append(["DomainGroup","DNS","Not Configured","Atleast one should be configured",Fore.RED+"FAILED"+Fore.RESET])

            try:
                if dg["SEM1"] != "212.59.89.1":
                    dg_data.append(["DomainGroup","MgmtServer1",dg["SEM1"],"212.59.89.1",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    dg_data.append(["DomainGroup", "MgmtServer1", dg["SEM1"], "212.59.89.1", "PASSED"])
            except Exception as e:
                dg_data.append(["DomainGroup","MgmtServer1","Not Configured","212.59.89.1",Fore.RED+"FAILED"+Fore.RESET])

            try:
                if dg["SEM2"] != "212.59.89.17":
                    dg_data.append(["DomainGroup", "MgmtServer2", dg["SEM2"], "212.59.89.17", Fore.RED+"FAILED"+Fore.RESET])
                else:
                    dg_data.append(["DomainGroup", "MgmtServer2", dg["SEM2"], "212.59.89.17", "PASSED"])
            except Exception as e:
                dg_data.append(["DomainGroup", "MgmtServer2", "Not Configured", "212.59.89.17", Fore.RED+"FAILED"+Fore.RESET])

            try:
                if dg["IKev2Auth"] != "EAP":
                    dg_data.append(["DomainGroup","IKEv2Auth",dg["IKev2Auth"],"EAP",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    dg_data.append(["DomainGroup", "IKEv2Auth", dg["IKev2Auth"], "EAP", "PASSED"])
            except Exception as e:
                dg_data.append(["DomainGroup","IKEv2Auth","Not Configured","EAP",Fore.RED+"FAILED"+Fore.RESET])

            try:
                if dg["IKEEapType"] != "PAP":
                    dg_data.append(["DomainGroup","IKEEapType",dg["IKEEapType"],"PAP",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    dg_data.append(["DomainGroup", "IKEEapType", dg["IKEEapType"], "PAP", "PASSED"])
            except Exception as e:
                dg_data.append(["DomainGroup","IKEEapType","Not Configured","EAP",Fore.RED+"FAILED"+Fore.RESET])

            try:
                if "IKEv2AllowAuthEAP" in dg.keys():
                    if dg["IKEv2AllowAuthEAP"] == "disabled":
                        dg_data.append(["DomainGroup","IKEv2AllowAuthEAP","disabled","enabled",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    dg_data.append(["DomainGroup","IKEv2AllowAuthEAP","enabled","enabled","PASSED"])
            except Exception as e:
                dg_data.append(["DomainGroup","IKEv2AllowAuthEAP","Unable to find key","enabled",Fore.RED+"FAILED"+Fore.RESET])

            try:
                if dg["ServerCertificate"] != "IPsec":
                    dg_data.append(["DomainGroup","ServerCertificate",dg["ServerCertificate"],"IPsec",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    dg_data.append(["DomainGroup", "ServerCertificate", dg["ServerCertificate"], "IPsec", "PASSED"])
            except Exception as e:
                dg_data.append(["DomainGroup","ServerCertificate","Not Configured","IPsec",Fore.RED+"FAILED"+Fore.RESET])

            try:
                if dg["RadiusState1"] != "enabled":
                    dg_data.append(["DomainGroup","RadiusState1",dg["RadiusState1"],"enabled",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    try:
                        if dg["RadiusAuthHost1"] != "10.0.1.140" or dg["RadiusAuthPassword1"] != "crypt:2cb46e2cdf973ce030319173664f6add90330ae34f71dc74":
                            dg_data.append(["DomainGroup","RadiusAuthHost1/Password1",dg["RadiusAuthHost1"]+"/"+"crypt paswd","10.0.1.140/<Look in passpack>",Fore.RED+"FAILED"+Fore.RESET])
                        else:
                            dg_data.append(["DomainGroup", "RadiusAuthHost1/Password1",dg["RadiusAuthHost1"]+"/"+"crypt paswd","10.0.1.140/<Look in passpack>", "PASSED"])
                    except Exception as e:
                        dg_data.append(["DomainGroup","RadiusAuthHost1/Password1","NA or set at Server Template","10.0.1.140/<Look in passpack>",Fore.RED+"FAILED"+Fore.RESET])
            except Exception as e:
                dg_data.append(["DomainGroup","RadiusState1","Not Configured","enabled",Fore.RED+"FAILED"+Fore.RESET])

            try:
                if dg["RadiusState2"] != "enabled":
                    dg_data.append(["DomainGroup","RadiusState2",dg["RadiusState2"],"enabled",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    try:
                        if dg["RadiusAuthHost2"] != "10.0.201.85" or dg["RadiusAuthPassword2"] != "crypt:2cb46e2cdf973ce030319173664f6add90330ae34f71dc74":
                            dg_data.append(["DomainGroup","RadiusAuthHost2/Password2",dg["RadiusAuthHost2"]+"/"+"crypt paswd","10.0.201.85/<Look in passpack>",Fore.RED+"FAILED"+Fore.RESET])
                        else:
                            dg_data.append(["DomainGroup", "RadiusAuthHost2/Password2",dg["RadiusAuthHost2"]+"/"+"crypt paswd","10.0.201.85/<Look in passpack>", "PASSED"])
                    except Exception as e:
                        print(e)
                        dg_data.append(["DomainGroup","RadiusAuthHost2/Password2","NA or set at Server Template","10.0.201.85/<Look in passpack>",Fore.RED+"FAILED"+Fore.RESET])
            except Exception as e:
                dg_data.append(["DomainGroup","RadiusState2","Not Configured","enabled",Fore.RED+"FAILED"+Fore.RESET])



            try:
                if not dg["IPPools"]:
                    dg_data.append(["DomainGroup","IPPools",dg["IPPools"]["IPPool"],"Pool details should be complete",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    if not isinstance(dg["IPPools"]["IPPool"],list):
                        dg_data.append(["DomainGroup", "IPPools", dg["IPPools"]["IPPool"]["PoolNr"] + "/" + (dg["IPPools"]["IPPool"]["PoolBegin"] + "-" + dg["IPPools"]["IPPool"]["PoolEnd"]), "Pool details should be complete","PASSED"])
                    elif len(dg["IPPools"]["IPPool"]) > 1:
                        errors_list.append("IP Pool should not be more than 1")
                        for i in range(len(dg["IPPools"]["IPPool"])):
                            #print(i)
                            dg_data.append(["DomainGroup", "IPPools", dg["IPPools"]["IPPool"][i]["PoolNr"] + "/" + (dg["IPPools"]["IPPool"][i]["PoolBegin"] + "-" + dg["IPPools"]["IPPool"][i]["PoolEnd"]), "Pool details should be complete","PASSED"])
                    else:
                        dg_data.append(["DomainGroup","IPPools","Not Configured","Pool details should be complete",Fore.RED+"FAILED"+Fore.RESET])                        
            except Exception as e:
                dg_data.append(["DomainGroup","IPPools","Not Configured","Pool details should be complete",Fore.RED+"FAILED"+Fore.RESET])



            try:
                if dg["IPPools"]:
                    flag = 0
                    if not "None" in local_subnet[nexus]:
                        if not isinstance(dg["IPPools"]["IPPool"],list):
                            for subnet in local_subnet[nexus]:
                                if ipaddress.ip_address(dg["IPPools"]["IPPool"]["PoolBegin"]) in ipaddress.ip_network(subnet) and ipaddress.ip_address(dg["IPPools"]["IPPool"]["PoolEnd"]) in ipaddress.ip_network(subnet):
                                    dg_data.append(["Network Test","IPPool","IPs are part of ANMC "+ subnet,"IPs should be part of ANMC subnet","PASSED"])
                                    flag = 1
                            if flag == 0:
                                dg_data.append(["Network Test","IPPool","IPs are not part of ANMC "+ subnet,"IPs should be part of ANMC subnet",Fore.RED+"FAILED"+Fore.RESET])
                        else:
                            for i in range(len(dg["IPPools"]["IPPool"])):
                                flag = 0
                                for subnet in local_subnet[nexus]:
                                    if ipaddress.ip_address(dg["IPPools"]["IPPool"][i]["PoolBegin"]) in ipaddress.ip_network(subnet) and ipaddress.ip_address(dg["IPPools"]["IPPool"][i]["PoolEnd"]) in ipaddress.ip_network(subnet):
                                        dg_data.append(["Network Test","IPPool","Pool "+dg["IPPools"]["IPPool"][i]["PoolNr"]+" IPs are part of ANMC "+ subnet,"Pool "+dg["IPPools"]["IPPool"][i]["PoolNr"]+" IPs should be part of ANMC subnet","PASSED"])
                                        flag = 1
                                if flag == 0:
                                    dg_data.append(["Network Test","IPPool","Pool "+dg["IPPools"]["IPPool"][i]["PoolNr"]+" IPs are not part of ANMC "+ subnet,"Pool "+dg["IPPools"]["IPPool"][i]["PoolNr"]+" IPs should be part of ANMC subnet",Fore.RED+"FAILED"+Fore.RESET])
                    else:
                        dg_data.append(["Network Test","IPPool","ANMC subnet not configured","IPs should be part of ANMC subnet",Fore.RED+"FAILED"+Fore.RESET])

            except Exception as e:
                #print(e)
                errors_list.append(e)


            try:
                if dg["IPPools"]:
                    if not isinstance(dg["IPPools"]["IPPool"],list):
                        if int(dg["IPPools"]["IPPool"]["PoolNr"]) > 0 and ipaddress.ip_address(dg["IPPools"]["IPPool"]["PoolBegin"]) < ipaddress.ip_address(dg["IPPools"]["IPPool"]["PoolEnd"]):
                            dg_data.append(["Network Test","IPPool","Begin IP comes before End IP","Begin IP comes before End IP","PASSED"])
                        else:
                            dg_data.append(["Network Test","IPPool","Begin IP comes after End IP","Begin IP comes before End IP",Fore.RED+"FAILED"+Fore.RESET])
                    else:
                        for i in range(len(dg["IPPools"]["IPPool"])):
                            if int(dg["IPPools"]["IPPool"][i]["PoolNr"]) > 0 and ipaddress.ip_address(dg["IPPools"]["IPPool"][i]["PoolBegin"]) < ipaddress.ip_address(dg["IPPools"]["IPPool"][i]["PoolEnd"]):
                                dg_data.append(["Network Test","IPPool","Pool "+dg["IPPools"]["IPPool"][i]["PoolNr"]+" Begin IP comes before End IP","Pool "+dg["IPPools"]["IPPool"][i]["PoolNr"]+" Begin IP comes before End IP","PASSED"])
                            else:
                                dg_data.append(["Network Test","IPPool","Pool "+dg["IPPools"]["IPPool"][i]["PoolNr"]+" Begin IP comes after End IP","Pool "+dg["IPPools"]["IPPool"][i]["PoolNr"]+" Begin IP comes before End IP",Fore.RED+"FAILED"+Fore.RESET])
            except Exception as e:
                #print(e)
                errors_list.append(e)

            try:
                if dg["RadiusForwardEAP"] != "enabled":
                    dg_data.append(["DomainGroup","RadiusForwardEAP",dg["RadiusForwardEAP"],"enabled",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    dg_data.append(["DomainGroup", "RadiusForwardEAP", dg["RadiusForwardEAP"], "enabled", "PASSED"])
            except Exception as e:
                dg_data.append(["DomainGroup", "RadiusForwardEAP", "Not Configured", "enabled", Fore.RED+"FAILED"+Fore.RESET])

            try:
                if not dg["VpnEndpoint"] or pop not in dg["VpnEndpoint"] or str(nexus) not in dg["VpnEndpoint"]:
                    dg_data.append(["DomainGroup","Map LinkProfile",dg["VpnEndpoint"],"VpnEndpoint should have same pop LP",Fore.RED+"FAILED"+Fore.RESET])
                else:
                    dg_data.append(["DomainGroup", "Map LinkProfile", dg["VpnEndpoint"], "VpnEndpoint should have same pop LP","PASSED"])
            except Exception as e:
                dg_data.append(["DomainGroup","Map LinkProfile","Not Configured","VpnEndpoint should have same pop LP",Fore.RED+"FAILED"+Fore.RESET])

    return(dg_data)

## function to report errors to Admin
def report_admin(func="func",err="err",err_list="err_list"):
    try:
        url = 'https://hook.eu1.make.com/b6d397uv8573gmpvac99g9raa7kadapd'
        headers = {'Content-Type': 'application/json'}
        user = os.getlogin()

        payload = json.dumps({
            "func" : func,
            "err" : str(err),
            "err_list" : err_list,
            "user" : user
        })
        response = requests.request("POST", url, headers=headers,verify=False,data=payload,timeout=5)
    except Exception as e:
        print(e)
        exit(1)


## Main function starts here
def main_starts_here() -> None:

    try:
        global errors_list
        errors_list = []
    #clear screen
        if (os.name == 'posix'):
            os.system('clear')
        else:
            os.system('cls')
    #getting user input and validating
        input = get_user_input()

    #get arvpn_id to nexus mapping
        print("Getting ARVPN details using EE API....")
        arvpn_dict,cust_code,cust_id,local_subnet,site_name,pop_edge_ip = find_arvpnID_mapping(input)

    #get vpn tunnel status
        print("Checking IPSec Tunnel Status using EE API....")
        tunnel_info = get_vpn_tunnel_status(input,cust_id)


    #get arvpn_id to arvpn server mapping
        final_data = find_arvpn_server(arvpn_dict)
        #print(final_data)

        t = Texttable(max_width=0)
        t.set_deco(Texttable.HEADER | Texttable.BORDER | Texttable.VLINES)

        now = datetime.now()
        now_converted = now.strftime("%d_%m_%Y@%H_%M")
        try:
            if not os.path.exists('output'):
                os.mkdir('output')

        except Exception as e:
            print(e)
            func = "folder creation"
            errors_list.append("Ended into exception while creating/handling output directory")
            print("Ended into exception while creating/handling output directory.")
            report_admin(func,e,errors_list)

        file = "nx{}-{}.csv".format(input,now_converted)
        #print(file)
        f = open(os.path.join("output",file),'w+')
        #print(f)
        writer = csv.writer(f)


    ## iterating over each nexus and its server to fetch data
        for nexus,arvpn_server in final_data.items():
            global_list = []
            link_profiles = []
            domain_groups = []
            device = {
                "device_type": "linux",
                "host": arvpn_server,
                "use_keys": True,
                "key_file" : user_data.key_file,
                "ssh_config_file": user_data.ssh_config_file,
                "conn_timeout" : 100,
                "banner_timeout" : 50,
            }


            try:
                print("Logging into ARVPN server to read config....")
                with ConnectHandler(**device) as net_connect:
                    try:
                        #ifconfig_output = net_connect.send_command("ifconfig bond0.16:pri122")
                        #ifconfig_data = jc.parse('ifconfig',ifconfig_output)
                        #private_edge_ip = ifconfig_data[0]['ipv4_addr']
                        output = net_connect.send_command("sudo cat /opt/ncp/ses/etc/cfg/srvlx.conf", read_timeout=10)
                        data = jc.parse('xml', output)
                        out_dict = dict(data)
                        pop = arvpn_server.split(".")[1]
                        try:
                            print("Fetching and validating Link Profile for nexus")
                            link_profiles = validate_link_profile(out_dict["ServerConfiguration"]["LinkProfiles"]["LinkProfile"], nexus,pop,cust_code,tunnel_info,pop_edge_ip)
                        except Exception as e:
                            print(e)
                            errors_list.append("unable to find matching Link Profiles on server {} for nexus {}".format(arvpn_server, nexus))
                        global_list = global_list + link_profiles


                        # get domain-groups and scrub data
                        try:
                            print("Fetching and validating Domain Group for nexus")
                            domain_groups = validate_domain_group(out_dict["ServerConfiguration"]["DomainGroups"]["DomainGroup"], nexus,pop,cust_code,tunnel_info,local_subnet,cust_id)
                        except Exception as e:
                            print(e)
                            errors_list.append("unable to find matching Domain Groups on server {} for nexus {}".format(arvpn_server, nexus))
                        global_list = global_list + domain_groups

                    except Exception as e:
                        print(e)
                        errors_list.append(e)

                writer.writerow(["****NEXUS:{}****".format(nexus)])
                print("\n")
                print(Back.GREEN+"****NEXUS:{}****".format(nexus)+Back.RESET)
                print("Site Info:")
                print("Customer_ID: {}".format(cust_id[nexus]))
                print("Name: {}".format(site_name[nexus]))
                print("Tunnel_Status: {}".format(tunnel_info[nexus]))
                if "None" in local_subnet[nexus]:
                    print("Local_Subnet: {}".format(local_subnet[nexus]))
                else:
                    print("Local_Subnet: {}".format(*local_subnet[nexus],sep=", "))
                #print("==============================================================================================================================================")
                global_list.insert(0, ["TYPE", "SECTION", "CONFIGURED", "EXPECTED", "VALIDATION"])
                t.reset()
                t.add_rows(global_list)
                writer.writerows(global_list)
                writer.writerow([""])
                writer.writerow(["#########","#########","#########","#########","#########","#########"])
                print(t.draw())
            except Exception as e:
                print(e)
                #pprint(device)
                print("**Unable to ssh {}**.\n->Please check your if Private key and ASA Proxy path is updated.\nCurrent Config:\n->Key = {}\n->ProxyPath = {}".format(device["host"],device["key_file"],device["ssh_config_file"]))
                errors_list.append("Unable to ssh {}".format(device["host"]))



        writer.writerow(["Errors:"])
        print("Errors:")
        if len(errors_list) == 0:
            writer.writerow(["No additional errors"])
            print("No additional errors")
            print("NOTE: This tool cannot validate PSK since its saved in encrypted format")
            print("NOTE: This tool cannot validate client config since its stored in db and not cannot be parsed")
        else:
            for error in errors_list:
                print(error)
                writer.writerow(error)
            print("NOTE: This tool cannot validate PSK since its saved in encrypted format")
            print("NOTE: This tool cannot validate client config since its stored in db and not cannot be parsed")
        f.close()

    except KeyboardInterrupt:
        print("\nKeyBoard Interrupt by user.....")
        exit(1)


## code starting point to check key_file and ssh_config_file.
if __name__ == "__main__":
    try:
        init()
        
        print("Validating if USER_DATA.PY file is up-to-date....")
        try:
            if not user_data.key_file != "":
                exit("key_file variable for private key is required in user_data. Please follow Installation steps!!!")
        except AttributeError:
            exit("key_file variable for private key is required in user_data. Please follow Installation steps!!!")

        try:
            if not user_data.ssh_config_file != "":
                exit("ssh_config_file variable for proxy path is required in user_data.\nDefault Path is:$HOME/.ssh/config. Please Check!!!")
        except AttributeError:
            exit("ssh_config_file variable for proxy path is required in user_data.\nDefault Path is:$HOME/.ssh/config. Please Check!!!")
        
        try:
            if not user_data.ee_url != "":
                exit("ee_url variable is required.\nPlease follow installation steps mentioned in Confluence!!\n")
        except AttributeError:
            exit("ee_url variable is required.\nPlease follow installation steps mentioned in Confluence!!\n")

    ## checking remote repo for updates
        print("Asking remote git if we need a code update....")
        try:
            repo = git.Repo('.')
            current = repo.head.commit
            repo.remotes.origin.pull()
            if current != repo.head.commit:
                exit("Your script has been auto-updated. Check Confluence for new added updates.\nYou can re-run the script to run validation!!\n")
        except git.exc.GitCommandError as error:
            print("Error pulling updated remote file: {}".format(error))
            repo.git.reset('--hard')
            repo.remotes.origin.pull()
            exit("Did you modify the script locally?\nAll local changes were reverted and new updates are loaded.\nYou may have to update user_data.py file again\n")
            #exit("Error in pulling repo from remote origin.\n Have you modified the file locally? or moved script to different path?\nIf yes, please delete folder and re-do steps mentioned in confluence")
        except Exception as e:
            print(e)
            exit("Error in pulling repo from remote origin.\n Have you modified the file locally? or moved script to different path?\nIf yes, please delete folder and re-do steps mentioned in confluence")


    #call main function
        main_starts_here()

    #check if user wants to run again
        try:
            run_again = str(input("\nWant to run again for different nexus?(y/n):")).lower()
            if run_again.startswith('y') or run_again == 'ok':
                main_starts_here()
            elif run_again.startswith('n'):
                exit("Got it!! BYE!!")
            else:
                exit("Can't understand. BYE!!")

        except KeyboardInterrupt:
            print("\nKeyBoard Interrupt by user.....")
            exit(1)

        except Exception as e:
            print(e)
            exit("Invalid input format.BYE!!")

    except KeyboardInterrupt:
        print("\nKeyBoard Interrupt by user.....")
        exit(1)







