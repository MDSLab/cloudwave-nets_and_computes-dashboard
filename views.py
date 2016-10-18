# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import ConfigParser
import json, os, subprocess
from datetime import datetime, timedelta

from django.http import HttpResponse   # noqa

from horizon import views
import logging
from openstack_dashboard.api import ceilometer, nova



LOG = logging.getLogger(__name__)


config = ConfigParser.RawConfigParser()
config.read(os.path.join(os.path.dirname(__file__), 'infrastructure.cfg'))

# HOSTS
hosts_list = [e.strip() for e in config.get('DEFAULT', 'hosts_list').split(',')]
host_metrics_list = [e.strip() for e in config.get('Host_metrics', 'host_metrics_list').split(',')]
host_units_list = [e.strip() for e in config.get('Host_metrics', 'host_units_list').split(',')]
host_ranges_list = [e.strip() for e in config.get('Host_metrics', 'host_ranges_list').split(',')]

# PHYSICAL NETWORKS
net_resources = [e.strip() for e in config.get('Network_metrics', 'net_resources').split(',')]
net_metrics_list = [e.strip() for e in config.get('Network_metrics', 'net_metrics_list').split(',')]
net_units_list = [e.strip() for e in config.get('Network_metrics', 'net_units_list').split(',')]
net_ranges_list = [e.strip() for e in config.get('Network_metrics', 'net_ranges_list').split(',')]

# VMS FOR THE DEMO
demo_vms_list = [e.strip() for e in config.get('Demo_vms', 'demo_vms_list').split(',')]


#Admin token and delta_t initialization
admin_token = ""
delta_t = 40

# For the hardware.network.outgoing.bytes.rate metric
outgoing_bytes_resources = ""


#************DEMO FLAG*******************
flag_demo = True
#****************************************



class IndexView(views.APIView):
    template_name = 'admin/infrastructurecw/index.html'

    #Admin token section
    global admin_token
    os.system("curl -i \'http://keystone:5000/v2.0/tokens\' -X POST -H \"Content-Type: application/json\" -H \"Accept: application/json\"  -d \'{\"auth\": {\"tenantName\": \"admin\", \"passwordCredentials\": {\"username\": \"admin\", \"password\": \"<PASSWORD>\"}}}\' > /tmp/adm_token; sed \'1,8d\' /tmp/adm_token > /tmp/temp; cat /tmp/temp | jq \'.access.token.id\' > /tmp/adm_token")
    admin_token = subprocess.check_output("sed -e \'s/\"//g\' /tmp/adm_token", shell=True).rstrip()

    # For the hardware.network.outgoing.bytes.rate metric
    global outgoing_bytes_resources
    outgoing_bytes_resources = r'{\"=\":{\"resource_id\":\"nova-cpt1.eth3.11\"}}, {\"=\":{\"resource_id\":\"nova-cpt2.eth3.11\"}}, {\"=\":{\"resource_id\":\"nova-cpt3.eth3.11\"}}}'



def change_label(metric_name):
    new_label = ""

    if metric_name.startswith("vlan."):
        metric_name = metric_name.split("vlan.")
        new_label = metric_name[1]

    elif metric_name.startswith("hardware."):
        metric_name = metric_name.split("hardware.")

        if metric_name[1] == "memory.used":
            new_label = "mem_used"

        elif metric_name[1] == "network.outgoing.bytes.rate":
            new_label = "outgoing.bytes"

        else:
            new_label = metric_name[1]

    elif metric_name.startswith("host."):
        metric_name = metric_name.split("host.")
        new_label = metric_name[1]

    else:
        return metric_name

    return new_label



def change_scale(metric_name, metric_volume):
    if metric_name == "outgoing.bytes" or metric_name == "bandwidth":
        #B/s -> Mb/s  => [  x / (1000^2) ] *8
        return round((8* metric_volume / 1000 / 1000),3)

    else:
        return metric_volume





# NET GAUGES Management
# ------------------------------------------------------------------------------------------------------------------------
def UpdateVlanGauges(request):
    global admin_token, delta_t

    nets = []
    query_resources = ""
    query_metrics = ""
    query = ""
    samples = []

    from_time = datetime.now()
    to_time = from_time - timedelta(seconds=delta_t)

    from_time = from_time.strftime("%Y-%m-%dT%H:%M:%S")
    to_time = to_time.strftime("%Y-%m-%dT%H:%M:%S")

    start = r'{\"<\":{\"timestamp\":\"'+from_time+r'\"}},'
    stop = r'{\">\":{\"timestamp\":\"'+to_time+r'\"}},'
    orderby = r'"orderby" : "[{\"timestamp\": \"DESC\"}, {\"counter_name\": \"ASC\"}]"'
    limit = r'"limit": 20'

    LOG.debug('VLANS GAUGES')

    #Composing the query and retrieve data samples
    #----------------------------------------------------------------
    for resource in net_resources:
        if query_resources == "":
            query_resources = r'{\"=\":{\"resource_id\":\"'+str(resource)+r'\"}}'
        else:
            query_resources += r',{\"=\":{\"resource_id\":\"'+str(resource)+r'\"}}'


    for i in range(len(net_metrics_list)):
        query_metrics = r'{\"=\":{\"counter_name\":\"'+str(net_metrics_list[i])+r'\"}}'

        #VERIFY IF IT WORKS!!!!!!
        #To avoid multiple samples with same values (CW issue)
        #if net_metrics_list[i] == "vlan.bandwidth":
        #    query_metrics += r',{\"=\": {\"metadata.unique\" : \"1\"}}'

        query = r'{"filter": "{\"and\":['+str(query_metrics)+r','+start+stop+r'{\"or\":['+str(query_resources)+r']}]}",'+str(orderby)+r','+str(limit)+'}'

        vlan_file = open("/tmp/vlans_query.txt", "w")
        vlan_file.write(query)
        vlan_file.close()
        result = subprocess.check_output("curl -X POST -H \'User-Agent: ceilometerclient.openstack.common.apiclient\' -H \'X-Auth-Token: "+str(admin_token)+"\' -H \'Content-Type: application/json\' --data @/tmp/vlans_query.txt http://ceilometer:8777/v2/query/samples", shell=True)#.rstrip()
        samples.append(json.loads(result))
        #LOG.debug('QUERY: %s', query)
    #LOG.debug('RESULT: %s', samples)
    #----------------------------------------------------------------


    #Composing the vector to return into the HttpResponse
    #----------------------------------------------------------------
    #LOG.debug('NET LEN: %s', len(samples))

    for i in range(len(samples)):
        for j in range(len(samples[i])):
            json_sample = samples[i][j]

            metric_display_name = change_label(json_sample["meter"])
            metric_pos = net_metrics_list.index(json_sample["meter"])
            metric_range = net_ranges_list[metric_pos]
            metric_unit = net_units_list[metric_pos]


            if len(nets) == 0:
                nets.append({"resource_id": json_sample["resource_id"], "metrics": [{"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume": change_scale(metric_display_name, json_sample["volume"]), "counter_unit": metric_unit, "range": metric_range}]})

            else:
                flag_other_net = True
                for k in range(len(nets)):
                    if nets[k]["resource_id"] == json_sample["resource_id"]:
                        flag_other_net = False
                        flag_insert = True
                        for l in range(len(nets[k]["metrics"])):
                            if nets[k]["metrics"][l]["counter_name"] == metric_display_name:
                                flag_insert = False
                                break

                        if flag_insert:
                            nets[k]["metrics"].append({"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume": change_scale(metric_display_name, json_sample["volume"]), "counter_unit": metric_unit, "range": metric_range})

                if flag_other_net:
                    nets.append({"resource_id": json_sample["resource_id"], "metrics": [{"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume": change_scale(metric_display_name, json_sample["volume"]), "counter_unit": metric_unit, "range": metric_range}]})


    #If no samples have been retrieved for a specific resource we add empty values
    if len(nets) != len(net_resources):
        for resource in net_resources:
            flag_insert = True
            for net in nets:
                if net["resource_id"] == resource:
                    flag_insert = False
                    break
            if flag_insert:
                nets.append({"resource_id": resource, "metrics": []})

    for net in nets:
        if len(net["metrics"]) != len(net_metrics_list):
            for i in range(len(net_metrics_list)):
                flag_insert = True
                for j in range(len(net["metrics"])):
                    if net["metrics"][j]["counter_name"] == change_label(net_metrics_list[i]):
                        flag_insert = False
                        break

                if flag_insert:
                    LOG.debug('NETS ----> Inserted missing metric: %s', change_label(net_metrics_list[i]))
                    net["metrics"].append({"counter_name": change_label(net_metrics_list[i]), "counter_volume": 0, "metric_position": i, "counter_unit": net_units_list[i], "range": net_ranges_list[i]})

    #Order by metric name position
    for net in nets:
        sorted_list = sorted(net["metrics"], key=lambda k: int(k["metric_position"]), reverse = False)
        #LOG.debug('SORTED: %s', sorted_list)
        net["metrics"] = sorted_list

    nets = sorted(nets, key=lambda k: k["resource_id"], reverse = False)

    LOG.debug('NETS %s', nets)
    #----------------------------------------------------------------

    return HttpResponse(json.dumps(nets),content_type="application/json")
# ------------------------------------------------------------------------------------------------------------------------


# HOSTS GAUGES Management
# ------------------------------------------------------------------------------------------------------------------------
def UpdateHostsGauges(request):
    global admin_token, delta_t

    hosts = []
    query_resources = ""
    query_metrics = ""
    query = ""
    samples = []
    vms_sum_samples = []

    from_time = datetime.now()
    to_time = from_time - timedelta(seconds=delta_t)

    from_time = from_time.strftime("%Y-%m-%dT%H:%M:%S")
    to_time = to_time.strftime("%Y-%m-%dT%H:%M:%S")

    start = r'{\"<\":{\"timestamp\":\"'+from_time+r'\"}},'
    stop = r'{\">\":{\"timestamp\":\"'+to_time+r'\"}},'
    orderby = r'"orderby" : "[{\"timestamp\": \"DESC\"}, {\"counter_name\": \"ASC\"}]"'
    limit = r'"limit": 20'

    limit_multiplier = 2

    LOG.debug('HOSTS GAUGES')

    #Composing the query and retrieve data samples
    #----------------------------------------------------------------

    for resource in hosts_list:
        if query_resources == "":
            query_resources = r'{\"=\":{\"resource_id\":\"'+str(resource)+r'\"}}'
        else:
            query_resources += r',{\"=\":{\"resource_id\":\"'+str(resource)+r'\"}}'

    for i in range(len(host_metrics_list)):

        query_metrics = r'{\"=\":{\"counter_name\":\"'+str(host_metrics_list[i])+r'\"}}'


        #if host_metrics_list[i] != "instances.mem_used":
        if host_metrics_list[i] != "hardware.memory.used":

            # For the hardware.network.outgoing.bytes.rate metric
            if host_metrics_list[i] == "hardware.network.outgoing.bytes.rate":
                query_resources = outgoing_bytes_resources

            query = r'{"filter": "{\"and\":['+str(query_metrics)+r','+start+stop+r'{\"or\":['+str(query_resources)+r']}]}",'+str(orderby)+r','+str(limit)+'}'

            host_file = open("/tmp/hosts_query.txt", "w")
            host_file.write(query)
            host_file.close()
            result = subprocess.check_output("curl -X POST -H \'User-Agent: ceilometerclient.openstack.common.apiclient\' -H \'X-Auth-Token: "+str(admin_token)+"\' -H \'Content-Type: application/json\' --data @/tmp/hosts_query.txt http://ceilometer:8777/v2/query/samples", shell=True)#.rstrip()
            samples.append(json.loads(result))
            LOG.debug('QUERY: %s', query)

        else:
            #For each metric not strictly related to the host but generated by the probe inside the vm we need to iterate each host's vms metric and gathering values
            if host_metrics_list[i] == "hardware.memory.used":
                query_metrics = r'{\"=\":{\"counter_name\":\"mem_used\"}}'

            for resource in hosts_list:
                vms_list = nova.hypervisor_search(request, resource)
                query_vms = ""

                #**************************************************************************************
                count = 0
                #Demo version
                if(flag_demo):
                    for vm in vms_list[0].servers:
                        if vm.get("uuid") in demo_vms_list:
                            if query_vms == "":
                                query_vms = r'{\"=\":{\"resource_id\":\"'+str(vm.get("uuid"))+r'\"}}'
                            else:
                                query_vms += r',{\"=\":{\"resource_id\":\"'+str(vm.get("uuid"))+r'\"}}'
                            count += 1

                #Standard version
                else:
                    for vm in vms_list[0].servers:
                        if query_vms == "":
                            query_vms = r'{\"=\":{\"resource_id\":\"'+str(vm.get("uuid"))+r'\"}}'
                        else:
                            query_vms += r',{\"=\":{\"resource_id\":\"'+str(vm.get("uuid"))+r'\"}}'
                        count += 1
                #**************************************************************************************

                if query_vms == "": 
                    LOG.debug('VMs query is empty!')
                    vms_sum_samples.append({"resource_id": resource, "counter_name": change_label(host_metrics_list[i]), "counter_volume": 0, "counter_unit": host_units_list[i], "range": host_ranges_list[i], "metric_position": i})
                    continue


                limit = r'"limit": '+str(limit_multiplier*len(vms_list[0].servers))
                #LOG.debug('LIMIT: %s', limit)
                if count == 1:
                    query = r'{"filter": "{\"and\":['+str(query_metrics)+r','+start+stop+str(query_vms)+r']}",'+str(orderby)+r','+str(limit)+'}'
                else:
                    query = r'{"filter": "{\"and\":['+str(query_metrics)+r','+start+stop+r'{\"or\":['+str(query_vms)+r']}]}",'+str(orderby)+r','+str(limit)+'}'

                host_file = open("/tmp/hosts_query.txt", "w")
                host_file.write(query)
                host_file.close()
                result = subprocess.check_output("curl -X POST -H \'User-Agent: ceilometerclient.openstack.common.apiclient\' -H \'X-Auth-Token: "+str(admin_token)+"\' -H \'Content-Type: application/json\' --data @/tmp/hosts_query.txt http://ceilometer:8777/v2/query/samples", shell=True)

                result = json.loads(result)
                LOG.debug('QUERY: %s', query)
                #LOG.debug('LEN RES: %s', len(result))

                temp_vms = []
                volume_sum = 0
                for res in result:
                    #LOG.debug('RES: %s', res["metadata"]["display_name"])
                    if len(temp_vms) == 0:
                        temp_vms.append({"vm_id": res["resource_id"], "volume": res["volume"]})
                        volume_sum += res["volume"]
                    else:
                        flag_insert_vms = True
                        for j in range(len(temp_vms)):
                            if temp_vms[j]["vm_id"] == res["resource_id"]:
                                flag_insert_vms = False
                                break
                        if flag_insert_vms:
                            temp_vms.append({"vm_id": res["resource_id"], "volume": res["volume"]})
                            volume_sum += res["volume"]

                if volume_sum != 0:
                    volume_sum = round((volume_sum / 1024),2)

                vms_sum_samples.append({"resource_id": resource, "counter_name": change_label(host_metrics_list[i]), "counter_volume": volume_sum, "counter_unit": host_units_list[i], "range": host_ranges_list[i], "metric_position": i})

            #LOG.debug('SAMPLES MEM_USED: %s', vms_sum_samples)
    #----------------------------------------------------------------



    #Composing the vector to return into the HttpResponse
    #----------------------------------------------------------------
    #LOG.debug('HOST: %s', len(samples))

    for i in range(len(samples)):
        for j in range(len(samples[i])):
            json_sample = samples[i][j]

            metric_display_name = change_label(json_sample["meter"])
            metric_pos = host_metrics_list.index(json_sample["meter"])
            metric_range = host_ranges_list[metric_pos]
            metric_unit = host_units_list[metric_pos]

            #Used ONLY to manage the hardware.network.outgoing.bytes.rate samples which have "nova-cpt1.eth3.11" like string as resource_id
            cpt = json_sample["resource_id"].split('.')
            json_sample["resource_id"] = cpt[0]

            #TEST: skip nova-cpt1 metrics! TBR
            #if json_sample["resource_id"] == "nova-cpt1": continue

            if len(hosts) == 0:
                hosts.append({"resource_id": json_sample["resource_id"], "metrics": [{"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume": change_scale(metric_display_name, json_sample["volume"]), "counter_unit": metric_unit, "range": metric_range}]})

            else:
                flag_other_host = True
                for k in range(len(hosts)):
                    if hosts[k]["resource_id"] == json_sample["resource_id"]:
                        flag_other_host = False
                        flag_insert = True
                        for l in range(len(hosts[k]["metrics"])):
                            if hosts[k]["metrics"][l]["counter_name"] == metric_display_name:
                                flag_insert = False
                                break

                        if flag_insert:
                            hosts[k]["metrics"].append({"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume": change_scale(metric_display_name, json_sample["volume"]), "counter_unit": metric_unit, "range": metric_range})

                if flag_other_host:
                    hosts.append({"resource_id": json_sample["resource_id"], "metrics": [{"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume": change_scale(metric_display_name, json_sample["volume"]), "counter_unit": metric_unit, "range": metric_range}]})

    #LOG.debug('PRE HOST: %s', hosts)



    #If no samples have been retrieved for a specific resource we add empty values
    if len(hosts) != len(hosts_list):
        for elem in hosts_list:
            flag_insert = True
            for host in hosts:
                if host["resource_id"] == elem:
                    flag_insert = False
                    break
            if flag_insert:
                hosts.append({"resource_id": elem, "metrics": []})


    for host in hosts:
        for vms_sum in vms_sum_samples:
            if host["resource_id"] == vms_sum["resource_id"]:
                host["metrics"].append({"counter_name": vms_sum["counter_name"], "counter_volume": vms_sum["counter_volume"], "metric_position": vms_sum["metric_position"], "counter_unit": vms_sum["counter_unit"], "range": vms_sum["range"]})
                break

        if len(host["metrics"]) != len(host_metrics_list):
            for i in range(len(host_metrics_list)):
                flag_insert = True
                for j in range(len(host["metrics"])):
                    if host["metrics"][j]["counter_name"] == change_label(host_metrics_list[i]):
                        flag_insert = False
                        break

                if flag_insert:
                    LOG.debug('HOSTS ----> Inserted missing metric: %s', change_label(host_metrics_list[i]))
                    host["metrics"].append({"counter_name": change_label(host_metrics_list[i]), "counter_volume": 0, "metric_position": i, "counter_unit": host_units_list[i], "range": host_ranges_list[i]})


    #Order by metric name position
    for host in hosts:
        sorted_list = sorted(host["metrics"], key=lambda k: int(k["metric_position"]), reverse = False)
        #LOG.debug('SORTED: %s', sorted_list)
        host["metrics"] = sorted_list

    #Order by resource_id
    hosts = sorted(hosts, key=lambda k: k["resource_id"], reverse = False)
    LOG.debug('HOSTS: %s', hosts)

    #----------------------------------------------------------------
    return HttpResponse(json.dumps(hosts),content_type="application/json")

# ------------------------------------------------------------------------------------------------------------------------
