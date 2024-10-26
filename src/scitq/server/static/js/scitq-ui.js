var flavors = {date:0};
var flavor_names = [];
var regions = [];
var providers = [];
var flavor_detail = new Map();
var flavor_region = new Map();
var flavor_regional_detail = new Map();
var flavor_provider = new Map()

function worker_concurrency_change(worker_id, change,i) {
    //socket.emit('concurrency_change', {object: 'worker', id: worker_id, change:change})
    $.ajax({url: '/ui/concurrency_change', data: {object: 'worker', id: worker_id, change:change} });
    workers[i].concurrency += change;
    if (workers[i].concurrency<0) {
        workers[i].concurrency=0;
    }
    document.getElementById(`concurrency-${worker_id}`).innerHTML=workers[i].concurrency;
}
function worker_prefetch_change(worker_id, change,i) {
    //socket.emit('prefetch_change', {object: 'worker', id: worker_id, change:change})
    $.ajax({url: '/ui/prefetch_change', data: {object: 'worker', id: worker_id, change:change} });
    workers[i].prefetch += change;
    if (workers[i].prefetch<0) {
        workers[i].prefetch=0;
    }
    document.getElementById(`prefetch-${worker_id}`).innerHTML=workers[i].prefetch;
}
function add_worker(concurrency, prefetch, flavor, region, provider, batch, number) {
    console.log('Launching new workers: concurrency:',concurrency,
        'flavor:',flavor, 'region:',region, 'provider:',provider, 'batch:',batch, 'number:',number);
    //socket.emit('create_worker', {concurrency: concurrency, prefetch: prefetch, 
    //    flavor: flavor, region: region, batch:batch, number: number});
    $.ajax({url: '/ui/create_worker', data:{concurrency: concurrency, prefetch: prefetch, 
        flavor: flavor, region: region, provider: provider, batch:batch, number: number} });
}
function worker_status2class(status) {
    return {
        'failed':'danger',
        'paused':'warning',
        'offline':'secondary',
        'running':'primary',
        }[status]||'dark'; 
}

async function get_workers() {
    console.log('Fetching workers...');
    await $.getJSON('/ui/get/', {
                object: 'workers'
            }, async function(data) {

        workers = data.workers;
        tasks_per_status = data.tasks_per_status;
        console.log('Received workers ',workers);
        console.log('Received tasks per status ',tasks_per_status);

        for (task_status of ['pending','assigned','accepted','running','failed','succeeded']) {
            document.getElementById(`${task_status}-tasks`).value = `${capitalize(task_status)}: ${tasks_per_status[task_status]||0}`;
        }
        
        
        worker_table = '';
        for (i=0; i<workers.length; i++) {
            
            worker_table += `
    <tr class="" >
        <td>
            <div title="${disp_flavor(workers[i].flavor,workers[i].provider,workers[i].region)}" class="information-tip-light">
                <form target="_blank" method="post" action='/ui/task/'>
                    <input type="hidden" name="worker_filter" value="${workers[i].name}">
                    <input type="submit" id="worker-${i}-tasks" value="${workers[i].name}" class="btn btn-outline-dark border-0">
                </form>
            </div>
        </td>
        <td class="" id="batch-name-${workers[i].worker_id}" style="padding:0">
            <form target="_blank" method="post" action='/ui/task/'>
                <input type="hidden" name="batch_filter" value="${(workers[i].batch==null?'-':workers[i].batch)}">
                <input type="submit" id="worker-${i}-batch" value="${(workers[i].batch==null?'':workers[i].batch)}" class="btn btn-outline-dark border-0">
            </form>
            <button type="button" onclick="ChangeBatch('${workers[i].worker_id}','${i}'); pause()" class="btn btn-sm" style="margin-top:0.5em;">
                ${svg_edit}
            </button>
        </td>
        <td class="text-center text-${worker_status2class(workers[i].status)}" title="${workers[i].status}" id="worker-status-${workers[i].worker_id}">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-circle-fill " viewBox="0 0 16 16">
                <circle cx="8" cy="8" r="8"/>
            </svg>
        </td>
        <td>
            <div id="concurrency-${workers[i].worker_id}" style="float: left;margin-right: 0.1em;margin-left: 0.8em;margin-top:0.2em;">
                ${workers[i].concurrency}
            </div>
            <div class ="btn-group" style="float: left;margin-top:0.2em;">
                <button class="btn btn-outline-dark btn-sm" onClick="worker_concurrency_change(${workers[i].worker_id},1,${i})"
                        style="width: 21px;height: 23px;padding: 0px 3px 0px 3px;">
                    +
                </button>
                <button class="btn btn-outline-dark btn-sm" onClick="worker_concurrency_change(${workers[i].worker_id},-1,${i})"
                        style="width: 21px;height: 23px;padding: 0px 3px 0px 3px;">
                    -
                </button>
            </div>
        </td>
        <td>
            <div id="prefetch-${workers[i].worker_id}" style="float: left;margin-right: 0.1em;margin-left: 0.6em;margin-top:0.2em;">
                ${workers[i].prefetch}
            </div>
            <div class ="btn-group" style="float: left;margin-top:0.2em;">
                <button class="btn btn-outline-dark btn-sm" onClick="worker_prefetch_change(${workers[i].worker_id},1,${i})" 
                        style="width: 21px;height: 23px;padding: 0px 3px 0px 3px;">
                    +
                </button>
                <button class="btn btn-outline-dark btn-sm" onClick="worker_prefetch_change(${workers[i].worker_id},-1,${i})"
                        style="width: 21px;height: 23px;padding: 0px 3px 0px 3px;">
                    -
                </button>
            </div>
        </td>
        <td>
            <form target="_blank" method="post" action='/ui/task/'>
                <input type="hidden" name="worker_filter" value="${workers[i].name}">
                <input type="hidden" name="status_filter" value="accepted">
                <input type="submit" id="worker-${i}-accepted" value="${workers[i].accepted}" class="btn btn-outline-dark border-0">
            </form>
        </td>
        <td>
            <form target="_blank" method="post" action='/ui/task/'>
                <input type="hidden" name="worker_filter" value="${workers[i].name}">
                <input type="hidden" name="status_filter" value="running">
                <input type="submit" id="worker-${i}-accepted" value="${workers[i].running}" class="btn btn-outline-dark border-0">
            </form>
        </td>
        <td>
            <form target="_blank" method="post" action='/ui/task/'>
                <input type="hidden" name="worker_filter" value="${workers[i].name}">
                <input type="hidden" name="status_filter" value="succeeded">
                <input type="submit" id="worker-${i}-accepted" value="${workers[i].succeeded}" class="btn btn-outline-dark border-0">
            </form>
        </td>
        <td>
            <form target="_blank" method="post" action='/ui/task/'>
                <input type="hidden" name="worker_filter" value="${workers[i].name}">
                <input type="hidden" name="status_filter" value="failed">
                <input type="submit" id="worker-${i}-accepted" value="${workers[i].failed}" class="btn btn-outline-dark border-0">
            </form>
        </td>
        <td>
            <small>${workers[i].load==null?'':workers[i].load}</small>
        </td>
        <td>
            <small>${workers[i].memory==null?'':workers[i].memory}</small>
        </td>
        ${(workers[i].stats!=undefined && typeof(workers[i].stats)=='object'?(`
            <td>
                <small>${workers[i].stats.load}</small>
            </td>
            <td>
                <small>
                    <table>
                        <tr>
                            <td style="white-space: nowrap;">
                                ${workers[i].stats.disk.usage.join('</td></tr><tr><td>').replaceAll(':','</td><td width="99">')}
                            </td>
                        </tr>
                    </table>
                </small>
            </td>
            <td>
                <small>
                    ${workers[i].stats.disk.speed+'<br/>'+workers[i].stats.disk.counter}
                </small>
            </td>
            <td>
                <small>
                    ${workers[i].stats.network.speed+'<br/>'+workers[i].stats.network.counter}
                </small>`):
            '<small><td>-</td><td>-</td><td>-</td><td>-</td></small>')
        }
        <td>
            <button type="button" title="${workers[i].status!='paused'?'pause':'resume'}" onclick="PauseUnpauseWorker(${workers[i].worker_id},${i})" 
                    class="btn btn-outline-dark btn-sm" id="pause-${workers[i].worker_id}">
                ${workers[i].status!='paused'?svg_pause:svg_resume}
            </button>
            <button type="button" title="clean" onclick="CleanWorker(${workers[i].worker_id})" 
                    class="btn btn-outline-dark btn-sm">
                ${svg_wipe}
            </button>
            <button type="button" title="restart" onclick="RestartWorker(${workers[i].worker_id})" 
                    class="btn btn-outline-dark btn-sm">
                ${svg_restart}
            </button>
            <button type="button" title="delete" onclick="DeleteWorker(${workers[i].worker_id})" 
                    class="btn btn-outline-dark btn-sm">
                ${svg_trash}
            </button>
        </td>
    </tr>\n`;
        }


        document.getElementById("worker-table-body").innerHTML = worker_table;
        await get_jobs();
    });
    await update_flavors(flavors);
};

function push_unique(item, l) {
    if (l.indexOf(item) === -1 && item !== '') {
        l.push(item);
        return(true);
    }
    else return(false);
}

function array2datalist(name, ar) {
    datalist = document.getElementById(name);
    datalist.textContent = '';
    //var datalist = document.createElement('datalist');
    //datalist.id = name;
    //document.body.appendChild(datalist);
    ar.forEach(function(data) {
        var option = document.createElement('option')
        option.value = data
        datalist.appendChild(option)
    });
}  

async function update_flavors(flavors) {
    await $.getJSON('/ui/flavors/', {date:flavors.date}, function(data) {
        if (data.list!==undefined) {
            console.log('Refreshing flavors');
            flavors.list=data.list;
            flavors.date=data.date;
            flavor_names.length = 0;
            regions.length = 0;
            providers.length = 0;
            regions.push('auto');
            providers.push('auto');
            console.log(flavors);
            flavors.list.forEach( function(flavor) {
                flavor_regional_detail[`${flavor.name},${flavor.provider},${flavor.region}`]=flavor;
                if (push_unique(flavor.name, flavor_names)) {
                    flavor_detail[flavor.name]=flavor;
                    flavor_region[[flavor.name,flavor.provider]]=[flavor.region];
                    flavor_provider[flavor.name]=[flavor.provider];
                } else {
                    push_unique(flavor.region, flavor_region[[flavor.name,flavor.provider]]);
                    push_unique(flavor.provider, flavor_provider[flavor.name]);
                };
                push_unique(flavor.region, regions);
                push_unique(flavor.provider, providers);
            });
            array2datalist('flavor_names',flavor_names);
            array2datalist('regions', regions);
            array2datalist('providers', providers);
            update_with_flavor(document.getElementById('awf-flavor'));
        }
    });
}

function disp_flavor(name, provider, region) {
    if (typeof(name)=="object") {
        f=name;
        return `${f.name} : cpu:${f.cpu} ram:${f.ram} disk:${f.disk}`+(f.tags!=''?` tags:${f.tags}`:'')+(f.gpu?` gpu:${f.gpu}`:'')+
            `\nprovider:${f.provider}`;
    } else {
        f=flavor_regional_detail[`${name},${provider},${region}`];
        if (f==undefined) {
            return '';
        } else {
            return `${f.name} : cpu:${f.cpu} ram:${f.ram} disk:${f.disk}`+(f.tags!=''?` tags:${f.tags}`:'')+(f.gpu?` gpu:${f.gpu}`:'')+
                `\nprovider:${provider}:${region} $/h:${f.cost}\n${f.available?"available:"+f.available+" ":""}eviction:${f.eviction}`;
        }
    }
}

function update_with_flavor(element) {
    info=document.getElementById('flavor-detail');
    region_input=document.getElementById('awf-region');
    provider_input=document.getElementById('awf-provider');
    if (flavor_names.includes(element.value)) {
        flavor = flavor_detail[element.value];
        info.removeAttribute('style');
        info.textContent=disp_flavor(flavor);
        array2datalist('regions', flavor_region[[flavor.name,flavor.provider]]);
        array2datalist('providers', flavor_provider[flavor.name]);
        if (flavor_region[[flavor.name,flavor.provider]].length==1) {
            region_input.value=flavor_region[[flavor.name,flavor.provider]][0];
        } else if (region_input.value!='' && region_input.value!='auto' && !flavor_region[[flavor.name,flavor.provider]].includes(region_input.value)) {
            region_input.value='';
        };
        if (flavor_provider[flavor.name].length==1) {
            provider_input.value=flavor_provider[flavor.name][0];
        } else if (provider_input.value!='' && provider_input.value!='auto' && !flavor_provider[flavor.name].includes(provider_input.value)) {
            provide_input.value='';
        }

    }
    else {
        info.setAttribute('style', 'display:none');
        info.textContent='';
        array2datalist('regions', regions);
        array2datalist('providers', providers);
    }
}

//send an order to server to delete in db the worker
function DeleteWorker(worker_id){
    //socket.emit('delete_worker',{worker_id:worker_id});
    $.ajax({url: '/ui/delete_worker', data: {worker_id:worker_id} });
    console.log(('Deleting worker'));
}

//send an order to server to delete in db the worker
function CleanWorker(worker_id){
    //socket.emit('delete_worker',{worker_id:worker_id});
    $.ajax({url: '/ui/clean_worker', data: {worker_id:worker_id} });
    console.log(('Cleaning worker'));
}

//send an order to server to delete in db the worker
function RestartWorker(worker_id){
    //socket.emit('delete_worker',{worker_id:worker_id});
    $.ajax({url: '/ui/restart_worker', data: {worker_id:worker_id} });
    console.log(('Restarting worker'));
}



function PauseUnpauseWorker(worker_id,i){
    if (workers[i].status!='paused') {
        workers[i].status='paused';
        button_element = document.getElementById(`pause-${worker_id}`);
        button_element.innerHTML=svg_resume;
        button_element.title='resume';
    }
    else {
        workers[i].status='running';
        button_element = document.getElementById(`pause-${worker_id}`);
        button_element.innerHTML=svg_pause;
        button_element.title='pause'
    }

    status_element = document.getElementById(`worker-status-${worker_id}`);
    status_element.className=`text-center text-${worker_status2class(workers[i].status)}`;
    status_element.title=workers[i].status;
    
    $.ajax({url: '/ui/pause_unpause_worker', data: {id:worker_id,status:workers[i].status} });
    console.log(`Setting worker to ${workers[i].status}`);
}

//send an order to server to delete the job job_id
function DeleteJob(job_id){
    $.ajax({url: '/ui/delete_job', data: {job_id:job_id} })
    console.log(('Deleting job'));
}

//send an order to server to delete all jobs (succeeded then failed then pending)
function DeleteJobs(){
    $.ajax({url: '/ui/delete_jobs' })
    console.log(('Deleting jobs'));
}

//send an order to server to restart the job job_id
function RestartJob(job_id){
    $.ajax({url: '/ui/restart_job', data: {job_id:job_id} })
    console.log(('Restarting job'));
}



//Function that open a text area in order to modify the batch and send the modification when the key "enter" triggers
function ChangeBatch(id_worker,i){
    document.getElementById('batch-name-'+id_worker).innerHTML=`<input class="col-9" id=batch-name-input-${id_worker} 
                                value="${workers[i].batch==null?'':workers[i].batch}" autofocus  style="margin-top:0.5em;">
                            <a type="button" class="btn btn-outline-dark border-0" 
                                style="--bs-btn-padding-y: .10rem; --bs-btn-padding-x: .3rem; --bs-btn-font-size: .75rem;" 
                                onclick="HideChangeBatch('${id_worker}',${i})">X</a>`;
    document.getElementById('batch-name-input-'+id_worker).addEventListener("keypress",function(event){
        if (event.key==='Enter'){
            event.preventDefault();
            //socket.emit('change_batch',{batch_name : document.getElementById('batch-name-input-'+id_worker).value,worker_id:id_worker});
            new_batch = document.getElementById('batch-name-input-'+id_worker).value;
            $.ajax({url: '/ui/change_batch', 
                data: {batch_name : new_batch,worker_id:id_worker} });
            document.getElementById('batch-name-'+id_worker).innerHTML=`
                <form target="_blank" method="post" action='/ui/task/'>
                    <input type="hidden" name="batch_filter" value="${(new_batch==null?'-':new_batch)}">
                    <input type="submit" id="worker-${i}-batch" value="${(new_batch==null?'':new_batch)}" class="btn btn-outline-dark border-0">
                </form>
                <button type="button" onclick="ChangeBatch('${id_worker}','${i}'); pause()" class="btn btn-sm" style="margin-top:0.5em;">
                    ${svg_edit}
                </button>`;
            //pause=false;
            unpause();
        }
    })
}
function HideChangeBatch(id_worker,i){
    document.getElementById('batch-name-'+id_worker).innerHTML=`<a type="button" class="btn btn-outline-dark border-0">
            ${workers[i].batch==null?'':workers[i].batch}</a>
            <button type="button" onclick="pause(); ChangeBatch('${id_worker}',${i})" 
                    class="btn btn-sm" style="margin-top:0.5em;">
                ${svg_edit}
            </button>`;
    //pause=false;
    unpause();
}

//socket.on('jobs', function(data) {
async function get_jobs() {
    await $.getJSON('/ui/jobs', {}, function(data) {
        //while(pause){
        //    await sleep(5000);
        //}    
        console.log('jobs received', data);
        var action_pretify = {
            worker_create: "Create worker",
            worker_deploy: "Deploy worker",
            worker_destroy: "Destroy worker"
        } ;
        var table='';
        var status_name = {
            succeeded: "success",
            pending: "secondary",
            running: "warning",
            failed: "danger"
        } ;
        var status_action = {
            succeeded: 1,
            pending: 0,
            running: 0,
            failed: 1
        } ;
        if (data.jobs.length>0) {
            table = '<table class="table table-responsive text-center table-hover table-striped">\n' +
                '<thead class=" table-secondary"><tr><th>Job</th> <th>Target</th> <th>Status</th> <th style="width: 40em;">Details</th> <th>Latest update</th> <th>Action  <button type="button" title="delete"' +
                ' onclick="DeleteJobs()" class="btn btn-outline-dark btn-sm">' + 
                svg_trash + '</button> </th> </tr> </thead>\n'+
                '<tbody>\n';
            data.jobs.forEach(function(job){
                var action = '';
                if (['succeeded','failed','pending'].includes(job.status)) {
                    action = '<button type="button" title="delete" onclick="DeleteJob('+
                            job.job_id+
                            ')" class="btn btn-outline-dark btn-sm">' + svg_trash
                            +'</button>';
                }

                if (job.status=='failed') {
                    action += `<button type="button" title="delete" onclick="RestartJob(${job.job_id})"
                        class="btn btn-outline-dark btn-sm">${svg_restart}</button>`
                }

                if (job.log.length>60) {
                    truncated_part = '<span class="truncated" id="job'+job.job_id+'">'+job.log.substr(60,job.log.length)+'</span>';
                }
                else {
                    truncated_part = '';
                }

                table += '<tr>' 
                    +'<td>'+action_pretify[job.action]+'</td>'
                    +(job.target?`<td><div title="${disp_flavor(job.args.flavor,job.args.provider,job.args.region)}" class="information-tip-light">${job.target}</div></td>`:'<td></td>')
                    +'<td class="text-center text-'+status_name[job.status]+'" title ="'+job.status
                    +'"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor"class="bi bi-circle-fill " viewBox="0 0 16 16"><circle cx="8" cy="8" r="8"/></svg></td>'
                    +'<td style="text-align: left;">'+job.log.substr(0,60) + truncated_part
                    +(typeof(job.progression)=='number'?`<div class="job-progress-bar"><div class="job-progress" style="width:${job.progression}%"></div></div>`:'')
                    +'</td>' 
                    +`<td>${display_date(job.modification_date)}</td>`
                    +'<td>'+action+'</td>'
                    +'</tr>\n';
            });
            table += '</tbody></table>\n';
        }
        document.getElementById('jobs').innerHTML = table;
        my_collapse(); 
    });
}

var uncollapsed_elements = [];

function my_collapse() {
$('.truncated').hide() // Hide the text initially
.after('<a title="expand text" href="#">[...]</a>') // Create toggle button
.next().on('click', function (event) { // Attach behavior
    // manage memory
    var element_id=$(this).parent().children(0).attr("id");
    $(this).text() == '[...]' 
      ? uncollapsed_elements.push(element_id)
      : uncollapsed_elements = uncollapsed_elements.filter(item => item !== element_id);

    // prepare the button
    event.preventDefault();
    $(this).text() == '[^]' // Swap the html
      ? $(this).text('[...]').attr("title", "expand text")
      : $(this).text('[^]').attr("title", "collapse text");
    $(this).prev().toggle(); // Hide/show the text

});
// use memory to reset states
uncollapsed_elements.forEach(
 function(element_id) {
    $('#'+element_id).show();
    $('#'+element_id).next().text("[^]");
 }

);
}

//$( document ).ready( get_workers() );
$(document).ready( loop_if_online(get_workers,5000) );