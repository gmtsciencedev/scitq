MAX_CARACTERE_DIPLAYED_IN_CONTENT=1000;
MAX_DISPLAYED_ROW = 500;
  
var current_parameters = {};

function status2class(status) {
    return {
        'succeeded':'success',
        'failed':'danger',
        'running':'primary',
        'paused':'warning',
        'pending':'secondary',
        'assigned':'secondary',
        'accepted':'secondary',
        'terminated':'info'
        }[status]||'dark'; 
}

//var socket = io();
//getting param for the filter
url = new URL(window.location.href); 
var filter = new Map();
var windows_open=new Map();
var paused_task=new Map();
var commands = new Map();
var detailed_tasks = [];
color_table='secondary';
filter.set('sortby',url.searchParams.get('sortby'));
filter.set('worker',url.searchParams.get('worker'));
filter.set('status',url.searchParams.get('status'));
filter.set('batch',url.searchParams.get('batch'));
filter.set('show',url.searchParams.get('show'));

if (!filter.get('sortby')) { 
    order_by='task';
}
else if(filter.get('sortby')==='worker'){
    order_by='worker';
}
else if (filter.get('sortby')==='batch'){
    order_by='batch';
}
else {
    order_by='default'
}
//Keeping the right color of thead associated with the current tab
color_table = status2class(filter.get('show'));

//socket.on('connect', function() {
//    console.log('connecting');
//    socket.emit('get', {object: 'task', order_by: order_by, filter_by: filter.get('show'), detailed_tasks: detailed_tasks});
//    });

async function get_tasks(parameters) {
    //socket.on('task', async function(data){

    //some action such as modifying a action needs time to be done so the update of the page can be set on true 
    if (parameters===undefined) {
        parameters = {'object':'tasks'};
        if (detailed_tasks!==undefined) {
            parameters.detailed_tasks=detailed_tasks;
        }
    }
    else {
        parameters.object='tasks';
    }
    
    if (order_by!=undefined) {
        parameters.order_by=order_by
    }
    if (filter.get('worker')!=undefined) {
        parameters.worker=filter.get('worker')
    }

    await $.getJSON('/ui/get/', parameters, function(data) {
    
        tasks= data.tasks;
        console.log('Received tasks', tasks);
        select_worker =`<div>
            <label class="form-label" for="filter_by_worker">Worker:</label>
            <select id="filter_by_worker" name="worker" class="form-select col-md-3">
                <option value="" ${filter.get('worker')!=''?'':''}>-</option>`;
        select_batch =`<div>
            <label class="form-label" for="filter_by_batch">Batch:</label>
            <select id="filter_by_batch" name="batch" class="form-select" col-md-3>
                <option value="" ${filter.get('batch')!=''?'':'selected'}>Default</option>`;
        sort_by=`<label for="sortby" class="form-label">Sort by:</label>
                <select id="sortby" name="sortby" class="form-select">
                <option value="" ${filter.get('sortby')==''?'selected':''}>-</option>
                <option value="worker" ${filter.get('sortby')=='worker'?'selected':''}>worker</option>
                <option value="batch" ${filter.get('sortby')=='batch'?'selected':''}> batch</option></select>`;
        var list_worker = [];
        var list_batch = [];
        running_table='';
        succeeded_table='';
        failed_table='';
        all_table='';

        // complete workers and batches filters
        tasks.forEach(task => {
            // complete worker select with workers present in task list
            if (task['worker_id']!==null) {
                if (!list_worker.includes(task['worker_id'])) {
                    list_worker.push(task['worker_id']);
                    select_worker += `<option value="${task['worker_id']}" 
                                            ${filter.get('worker')==task['worker_id'].toString()?'selected':''}>
                                        ${task['worker_name']}
                                    </option>`;
                }
            }
            // complete batch select with batches included in task list
            if (!list_batch.includes(task['batch']) && task['batch']!=null) {
                list_batch.push(task['batch']);
                select_batch += `<option value="${task['batch']}"
                                    ${filter.get('batch')==task['batch']?'selected':''}>
                                    ${task['batch']}
                                </option>`;
            }
        });
        
        //According to the argument 'show' in the url that others views use, to open the right tab from another view
        task_table = create_table(filter.get('show'));

        select_worker +='</select>\n</div>';
        select_batch +='</select>\n</div>'
        
        document.getElementById("tasks-table-body").innerHTML=task_table;
        document.getElementById("filter_by_worker").innerHTML=select_worker;
        document.getElementById("filter_by_batch").innerHTML=select_batch;
        document.getElementById("sortby").innerHTML=sort_by;
        // Due to the update of the page every 5 seconds, this maintain the output to the bottom.
        for(element of document.getElementsByName('scroll')){
            element.scrollTop=999999;
        }
        console.log('detailed_tasks: '+detailed_tasks);
    });
}



//this function allows to change the chevron to the top or to the bottom according to the statement if it is open or not.
function modify_chevron(task_id,execution_id,keyword){
    var btn = document.getElementById(`chevron-${keyword}-${task_id}`);
    if( btn.value==='false' || btn.value===''){
        if (execution_id) {detailed_tasks.push(execution_id)};
        btn.innerHTML=chevron_up;
        btn.value=true;
        windows_open.set(keyword+'-'+task_id,'open'); // the displayed content are kept in memory due to the uptade of the page 
        element = document.getElementById("chevron-"+keyword+"-"+task_id);
        element.scrollTop=999999;
    }      
    else{
        remove_from_array(detailed_tasks,execution_id);
        btn.innerHTML=chevron_down;
        btn.value=false;
        windows_open.delete(keyword+'-'+task_id);
    }
}

function formatOutput(output, task_id, execution_id, style) {
    return output?`<div class="btn-group" role="group">
        <a class="btn btn-outline-dark border-0 text-white d-inline-block text-truncate text-center"
            style="max-width: 10em"
            data-bs-toggle="collapse" 
            href="#output-std-${task_id}" 
            role="button" 
            aria-expanded="false" 
            onclick="modify_chevron(${task_id},${execution_id},'output-${style}')" 
            aria-controls="collapseOutput">
            ${output}
        </a>
        <button class="btn btn-outline-dark border-0 text-white"
            data-bs-toggle="collapse" href="#output-${style}-${task_id}" 
            value="${windows_open.has('output-'+style+'-'+task_id)}" 
            id="chevron-output-${style}-${task_id}" 
            role="button" 
            aria-expanded="false" 
            aria-controls="collapseCommand" 
            onclick="modify_chevron(${task_id},${execution_id},'output-${style}')">
            ${windows_open.has('output-'+style+'-'+task_id)?chevron_up:chevron_down}
        </button>
    </div>`
    :'';
}

//Allows to get the right duration of a execution with the suitable unit
function getRuntime(diff_in_second){
    if (diff_in_second>3600*24) {
        return (diff_in_second/(3600*24)).toFixed(1)+'d';
    }
    else if(diff_in_second>3600){
        return (diff_in_second/3600).toFixed(1)+'h' ;
    }
    else if(diff_in_second>60){
        return (diff_in_second/60).toFixed(1)+'min';
        }
    return (diff_in_second).toFixed(1)+'s';
}

function displayMax(output) {
    return output?
                (output.length>=MAX_CARACTERE_DIPLAYED_IN_CONTENT?
                    output.substring(
                                output.length-1-MAX_CARACTERE_DIPLAYED_IN_CONTENT,
                                output.length-1)
                    :
                    output
                )
                :
                '';
}

//create a table same structure as in ui according to the type of task
function create_table(type_task){
    table='';
    all=false;
    if (type_task === 'terminated'){
        type_task = ['failed','succeeded'];
    }
    else if (type_task==='running'){
        type_task=['running','paused'];
    }
    else if (type_task==='pending'){
        type_task=['pending','assigned','accepted']
    }
    else if (['failed','succeeded'].includes(type_task)) {
        type_task =[type_task];
    }
    else {
        all=true
    }
    displayed_rows = 0; //count the number of row not to exceed an maximum of row (currently set at 50)


    // the information go through a filter settled by the arguments in the url that doesn't let it pass if it has not the exact information defined by the filter
    tasks.forEach((task,i) => {
        if (displayed_rows<MAX_DISPLAYED_ROW && (all || type_task.includes(task.status)) ) {
            if ( (!filter.get('worker') || task.worker_id==filter.get('worker')) &&
                 (!filter.get('batch')  || task.batch==filter.get('batch')) ) {
                displayed_rows++;
                var date_started = new Date(task['creation_date']+"+00");
                var date_end = new Date(task['modification_date']+"+00");
                var diff_in_second= Math.round((date_end.getTime()- date_started.getTime())/(1000));
                    
                //Change the color of the status' circle according to the task's status
                task_status = status2class(task['status']);

                table+=`<tr>
                    <td>
                        <h6 class="d-flex col-md-12"><h6>t:${task.task_id}</h6>
                            <h6> e:${task.execution_id||''}
                        </h6>
                    </td>
                    <td width ="5%" class="text-center">
                        ${task.name||''}
                    </td>
                    <td class="table-stripped text-center">
                        <div class="btn-group" role="group">
                            <a class="btn btn-outline-secondary border-0 text-dark text-truncate text-center" 
                                style="max-width: 10em;" data-bs-toggle="collapse" 
                                href="#command-${task.task_id}" 
                                id="button-command-${task.task_id}"
                                role="button" 
                                aria-expanded="false" 
                                aria-controls="collapseCommand" 
                                onclick="modify_chevron(${task.task_id},${task.execution_id},'command')">
                                ${task.command}
                            </a>
                        <button class="btn btn-outline-secondary border-0 text-dark" 
                            data-bs-toggle="collapse" 
                            href="#command-${task.task_id}" 
                            value="${windows_open.has('command-'+task.task_id)==true?"true":"false"}" 
                            id="chevron-command-${task.task_id}" 
                            role="button" 
                            aria-expanded="false" 
                            aria-controls="collapseCommand" 
                            onclick="modify_chevron(${task.task_id},${task.execution_id},'command')">
                            ${windows_open.has('command-'+task.task_id)?chevron_up:chevron_down}
                        </button>
                    </td>
                    <td width ="10%" class="text-center">
                        ${task.worker_name||''}
                    </td>
                    <td class="text-center">
                        ${task.batch||''}
                    </td>
                    <td class="text-center text-${task_status}" 
                        title="${task.status}">
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor"class="bi bi-circle-fill " viewBox="0 0 16 16"><circle cx="8" cy="8" r="8"/></svg>
                    </td>
                    <td class="text-center">
                        ${task.creation_date==null?'':(
                            date_started.getFullYear()+"-"+
                            (date_started.getMonth()+1)+"-"+
                            date_started.getDate()+" "+
                            date_started.getHours()+":"+
                            date_started.getMinutes()+":"+
                            date_started.getSeconds()
                        )}
                    </td>
                    <td class="text-center">
                        ${getRuntime(diff_in_second)}
                    </td>
                    <td class="table-dark text-center">
                        ${formatOutput(task.output,task.task_id,task.execution_id,'std')}
                    </td>
                    <td class="table-dark text-center">
                        ${formatOutput(task.error,task.task_id,task.execution_id,'err')}
                    </td>
                    <td class="text-center">
                        <div class="btn-group btn-group-sm" role="group" aria-label="Basic mixed styles example">
                            ${task.status=='paused'?
                            ('<button type="button" title="play" onclick="action_task(\''
                                    +task.task_id
                                    +'\',\'resume\')" class="btn btn-outline-dark">'
                                +svg_resume
                            +'</button>')
                            :''}
                            ${task.status=='running'?
                                ('<button type="button" title="pause" onclick="action_task(\''
                                        +task.task_id
                                        +'\',\'pause\')" class="btn btn-outline-dark">'
                                    +svg_pause
                                +'</button>'
                                +'<button type="button" title="stop" onclick="displayModal('
                                    +task.task_id+','+task.execution_id
                                    +',\'stop\')" class="btn btn-outline-dark">'
                                    +svg_stop
                                +'</button>'
                                +'<button type="button" title="break" onclick="displayModal('
                                        +task.task_id+','+task.execution_id
                                        +',\'break\')" class="btn btn-outline-dark">'
                                        +svg_break
                                +'</button>')
                                :''}
                                
                            <button type="button" title ="restart" 
                                onclick="action_task(${task.task_id},'restart')" 
                                class="btn btn-outline-dark">
                                ${svg_restart}
                            </button>
                            
                            <button type="button" title ="download" 
                                onclick="download(${task.task_id},${i})"
                                class="btn btn-outline-dark">
                                ${svg_download}
                            </button>
                
                            <button type="button" title="delete" 
                                onclick="displayModal(${task.task_id},${task.execution_id},'delete')" 
                                class="btn btn-outline-dark">
                                ${svg_delete}
                            </button>
                        </div>
                        <div id="task-modal-${task.task_id}" class="modal"></div>
                    </td>
                </tr>
                <tr class="collapse ${windows_open.has('command-'+task.task_id)?'show':''}"
                        id="command-${task.task_id}">
                    <td colspan="11" id="command-content-${task.task_id}">
                        <div class="d-flex">
                            <div class="p-2 w-100">
                                ${task.command}
                            </div>
                            <div class="p-2 flex-shrink-1">
                                <button type="button" tiltle="modify" 
                                        onclick="modify_command(${task.task_id},${i})" 
                                        class="btn btn-dark" 
                                        style="--bs-btn-padding-y: .10rem; --bs-btn-padding-x: .3rem; --bs-btn-font-size: .75rem;">
                                    modify
                                </button>
                            </div>
                        </div>
                    </td>
                </tr>
                <tr class="collapse ${windows_open.has('output-std-'+task.task_id)?'show':''} table-dark" 
                        id="output-std-${task.task_id}">
                    <td colspan="11" class ="border border-light border-5 border-top-0 " >
                        <div name="scroll" id="scroll-output-std-${task.task_id}" 
                                style="max-height:10em;max-width:100%;white-space: pre-line;" 
                                class="overflow-auto">
                            ${displayMax(task.output)}                            
                        </div>
                    </td>
                </tr>
                <tr class="collapse ${windows_open.has('output-err-'+task.task_id)?'show':''} table-dark" 
                        id="output-err-${task.task_id}">
                    <td colspan="11" class ="border border-light border-5 border-top-0  text-warning" >
                        <div name="scroll" id="scroll-output-err-${task.task_id}" 
                                style="max-height:10em;max-width:100%;white-space: pre-line;" 
                                class="overflow-auto">
                            ${displayMax(task.error)}
                        </div>
                    </td>
                </tr>`;
            }
        }
    });
    return table;
}

function displayModal(task_id, execution_id,type) {
    console.log(document.getElementById('task-modal-'+task_id));
    document.getElementById('task-modal-'+task_id).innerHTML=`
        <div class="modal-dialog modal-dialog-centered">
            <form class="modal-content">
                <div class="container">
                    <h3>${type}</h3>
                    <p>Are you sure you want to ${type} task_${task_id}${type==='delete'?' ':' execution_'+execution_id} ?</p>
                    <div class="clearfix">
                        <button type="button" class="btn btn-danger" 
                                onclick="document.getElementById('task-modal-${task_id}').style.display='none'; unpause()">
                            Cancel
                        </button>
                        <button type="button" class="btn btn-primary" 
                                onclick="action_task('${task_id}','${type}'); 
                                    document.getElementById('task-modal-${task_id}').style.display='none'; unpause()">
                            Confirm
                        </button>
                    </div>
                </div>
            </form>
        </div>`;
    document.getElementById('task-modal-'+task_id).style.display = "block";
    pause();
}

function download(task_id,i) {
    execution_id = tasks[i].execution_id;
    output = tasks[i].output;
    error = tasks[i].error;
    var element = document.createElement('a');
    // I used this code https://www.delftstack.com/fr/howto/javascript/javascript-download/ with some modifications
    if (output) {
        element.setAttribute('href', 'data:text/plain;charset=utf-8,' + encodeURIComponent(output));
        element.setAttribute('download', 'output-std-'+task_id+'-execution-'+execution_id);
        element.style.display = 'none';
        document.body.appendChild(element);
        element.click();
        document.body.removeChild(element);
    }
    if (error) {
        element.setAttribute('href', 'data:text/plain;charset=utf-8,' + encodeURIComponent(error));
        element.setAttribute('download', 'output-err-'+task_id+'-execution-'+execution_id);
        element.style.display = 'none';
        document.body.appendChild(element);
        element.click();
        document.body.removeChild(element);
    }
}

// I used the documentation of JSZip
function downloadAll(type){
    var zip = new JSZip();
    tasks.forEach(task => { 
        //the information go through a filter to have the same information that is showed by the view
        console.log(type);
        if (type==="all" || type === task.status) {
            console.log('1',filter.get('worker'));
            if ( (!filter.get('worker') || task.worker_name==filter.get('worker')) &&
                 (!filter.get('batch')  || task.batch==filter.get('batch')) ) {
                zip.folder("output-"+task.task_id);
                if (task.output) {
                    zip.file(`output-${task.task_id}/output-std-${task.task_id}-execution-${task.execution_id}.txt`,
                            task.output);
                }
                if (task.error) {
                    zip.file(`output-${task.task_id}/output-err-${task.task_id}-execution-${task.execution_id}.txt`,
                            task.error);
                }
            }
        }
    });
    zip.generateAsync({type:"blob"}).then(function (content) { // 1) generate the zip file
        saveAs(content, "scitq_outputs.zip");
        });
}
    
//Allows to switch betwween the different tabs and change the color of the thead
function show_tasks(type_task){
    document.getElementById("tasks-table-body").innerHTML=create_table(type_task);
    document.getElementById("downloadall").onclick=function() {downloadAll(type_task)};
    windows_open.clear();
    filter.set('show',type_task);
    color_table = status2class(type_task);
    document.getElementById("task_head").className ="text-center table-"+color_table+"";
}

//Send an action to the server
function action_task(task_id,type_action,command){
    if (type_action=='modify'){
        $.ajax({
            url: '/ui/task/action',
            data: {task_id:task_id,action:type_action,modification:command}
        });
    }
    else {
        $.ajax({
            url: '/ui/task/action',
            data: {task_id:task_id,action:type_action}
        });
    }
    console.log('Sending action');
}

//Open a textarea to modify a command.
function modify_command(task_id,i){
    command = tasks[i].command;
    content = document.getElementById("command-content-"+task_id);
    if (pause()) {
        content.innerHTML=`<form>
            <textarea id="textarea-${task_id}" class="form-control" rows="4">${command}</textarea>
            <button type="button" onclick="modify_command(${task_id},${i})" 
                    class="btn btn-danger" 
                    style="--bs-btn-padding-y: .10rem; --bs-btn-padding-x: .3rem; --bs-btn-font-size: .75rem;" >
                Cancel
            </button>
            <button type="button" class="btn btn-primary" 
                    style="--bs-btn-padding-y: .10rem; --bs-btn-padding-x: .3rem; --bs-btn-font-size: .75rem;" 
                    onclick="action_task(${task_id},'modify',document.getElementById('textarea-${task_id}').value);
                    modify_command(${task_id},${i})">
                Submit
            </button>
        </form>`;
    }
    else {
        unpause();
        content.innerHTML=`<div class="d-flex">
            <div class="p-2 w-100">
                ${command}
            </div>
            <div class="p-2 flex-shrink-1">
                <button type="button" tiltle="modify" 
                        onclick="modify_command(${task_id},${i})" 
                        class="btn btn-dark" 
                        style="--bs-btn-padding-y: .10rem; --bs-btn-padding-x: .3rem; --bs-btn-font-size: .75rem;">
                    modify
                </button>
            </div>
        </div>`;
    }
}

//the function required to be set after the texte area so it can get the value of it
//function submit_command(execution_id,i){
//return action_task(tasks[i][0],'modify',document.getElementById('textarea-'+execution_id).value);
//}

$(document).ready( loop_if_online(get_tasks,5000) );

// $(document).ready( get_tasks( {} ) );