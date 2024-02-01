
function batch_line(current_batch, workers_by_batch, 
        status_running, status_failed, status_succeeded, status_pending, total,
        stat_details) {
    //json_batch = current_batch.replace(' ','+');
    
    function task_button(task_status, task_count) {
        return `<form target="_blank" method="post" action='/ui/task/'>
            <input type="hidden" name="status_filter" value="${task_status}">
            <input type="hidden" name="batch_filter" value="${current_batch}">
            <input type="submit" class="btn btn-outline-dark border-0" value=${task_count}>
        </form>`
    }

    return `
    <tr>
        <td>
        </td>
        <td width ="5%">
            <form target="_blank" method="post" action='/ui/task/'>
                <input type="hidden" name="batch_filter" value="${current_batch}">
                <input type="submit" id="batch-tasks" value="${current_batch}" class="btn btn-outline-dark border-0">
            </form>
        </td>
        <td>
            ${workers_by_batch.get(current_batch)}
        </td>
        <td>
            <div class="progress border-1" style="margin-top:10px;">
                <div class="progress-bar${status_running==0?'':' progress-bar-striped progress-bar-animated'}
                        bg-danger"
                    role="progressbar" 
                    style="width:${status_failed/total*100}%" 
                    aria-valuenow="${status_failed/total*100}" 
                    aria-valuemin="0" 
                    aria-valuemax="100">
                </div>
                <div class="progress-bar ${status_running==0?'':' progress-bar-striped progress-bar-animated'}
                        bg-success" 
                    role="progressbar" 
                    style="width:${status_succeeded/total*100}%" 
                    aria-valuenow="24" 
                    aria-valuemin="0" 
                    aria-valuemax="100">
                </div>
            </div>
        </td>

        <td width ="10%" style="padding-top: 14px;">
            ${task_button('pending',status_pending)}
        </td>
        <td>
            ${task_button('running',status_running)}
        </td>
        <td>
            ${task_button('succeeded',status_succeeded)}
        </td>
        <td>
            ${task_button('failed',status_failed)}
        </td>
        <td>
            ${task_button('all',total)}
        </td>
        <td>
            ${stat_details}
        </td>
        <td>
            <div class="btn-group">
                <button type="button" 
                        title="simple pause" 
                        onclick="displayModal('${current_batch}','pause')" 
                        class="btn btn-outline-dark">
                    ${svg_pause}
                </button>
                <button type="button" 
                        title="go" 
                        onclick="displayModal('${current_batch}','go','${status_paused}')"
                        class="btn btn-outline-dark">
                    ${svg_restart}
                </button>
                <button type="button" 
                        title="stop" 
                        onclick="displayModal('${current_batch}','stop')"
                        class="btn btn-outline-dark">
                    ${svg_stop}
                </button>
                <button type="button" 
                        title="break" 
                        onclick="displayModal('${current_batch}','break')" 
                        class="btn btn-outline-dark">
                    ${svg_break}
                </button>
                <button type="button"
                        title="clear" 
                        onclick="displayModal('${current_batch}','clear')"
                        class="btn btn-outline-dark">
                    ${svg_delete}
                </button>
            </div>
            <div id="batch-modal-${current_batch}" class="modal">
            </div>
        </td>
    </tr>`;
}
    
async function get_batch() {
    await $.getJSON('/ui/get/', {
    object: 'batch'
    }, function(data) {
    //  socket.on('batch', async function(data){
        //some action such as modify a action needs time to be done so the update of the page can be set on true 

        batches= data.batches;
        workers=data.workers;
        console.log('Received batches', batches);
        console.log('Received workers', workers);
        batch_table = '';
        list_batch=[];
        workers_by_batch =new Map();
        // list al the worker in batches
        workers.forEach(worker => {
            workers_by_batch.set(worker.batch,worker.workers.replaceAll(',','<br/>'));
        });
        current_batch = undefined;
        batches.forEach(batch => {
            if (batch.batch!==current_batch) {
                // we encounter a new batch (and batches are sorted by batch so we ended previous one)
                if (current_batch!==undefined) {
                    // we are not at the begining we have a full batch in memory
                    batch_table += batch_line(current_batch, workers_by_batch, 
                        status_running, status_failed, status_succeeded, status_pending, total,
                        stat_details);
                }

                current_batch=batch.batch;
                total=0;
                status_running=0;
                status_failed=0;
                status_pending=0;
                status_succeeded=0;
                stat_details='';
                status_paused=0;
            }
            total += batch.count;
            
            if (['running','paused'].includes(batch.status)) {status_running+=batch.count;}
            else if (['pending','accepted'].includes(batch.status)) {status_pending+=batch.count;}
            else if (batch.status==='succeeded') {status_succeeded+=batch.count;}
            else if (batch.status==='failed') {status_failed+=batch.count;}
            
            if (batch.avg!==null) {
                stat_details += `
                    <div class="p-2 text-${batch.status==='succeeded'?'success':
                            batch.status==='failure'?'danger':
                            'normal'}">
                        ${batch.status}: ${batch.avg.toFixed(2)}
                            [${batch.min.toFixed(2)} - ${batch.max.toFixed(2)}]
                    </div>`;
            }
        });
        if (current_batch!==undefined) {
            batch_table += batch_line(current_batch, workers_by_batch, 
                status_running, status_failed, status_succeeded, status_pending, total,
                stat_details);
        }
        document.getElementById("batch-table-body").innerHTML=batch_table; 
    });
}

function displayModal(current_batch,type,status_paused=0) {
    //Status is only used with type = go.
    console.log(document.getElementById('batch-modal-'+current_batch));
    if(type==='pause'||type==='go') {
        document.getElementById('batch-modal-'+current_batch).innerHTML=
            `<div class="modal-dialog modal-dialog-centered">
                <form class="modal-content">
                    <div class="container">
                        <h3>${type}</h3>
                        <p>
                            Do you want to ${type==='go'?'start/restart the batch':type+' the batch'} 
                                ${current_batch} ${type==='go'?'and resume the tasks in pause ('+status_paused+') ?'
                                                        :
                                                        'and the tasks in progress ?'}
                        </p>
                        <div class="clearfix">
                            <button type="button" 
                                    class="btn btn-danger" 
                                    onclick="document.getElementById('batch-modal-${current_batch}').style.display='none'; 
                                        unpause()">
                                Cancel
                            </button>
                            <button type="button" 
                                    class="btn btn-warning" 
                                    onclick="action_batch('${current_batch}','${type}'); 
                                        document.getElementById('batch-modal-${current_batch}').style.display='none'; 
                                        unpause()">
                                Both
                            </button>
                            <button type="button" 
                                    class="btn btn-primary" 
                                    onclick="action_batch('${current_batch}','simple ${type}');
                                        document.getElementById('batch-modal-${current_batch}').style.display='none'; unpause()">
                                Only Batch
                            </button>
                        </div>
                    </div>
                </form>
            </div>`;
    }
    else
    {
        document.getElementById('batch-modal-'+current_batch).innerHTML=`
            <div class="modal-dialog modal-dialog-centered">
                <form class="modal-content"><div class="container">
                    <h3>${type}</h3>
                    <p>Are you sure you want to ${type} ${current_batch} ?</p>
                    <div class="clearfix">
                        <button type="button" 
                                class="btn btn-danger" 
                                onclick="document.getElementById('batch-modal-${current_batch}').style.display='none';
                                    unpause()" >
                            Cancel
                        </button>
                        <button type="button" 
                                class="btn btn-primary" 
                                onclick="action_batch('${current_batch}','${type}');
                                    document.getElementById('batch-modal-${current_batch}').style.display='none'; 
                                    unpause()">
                            Confirm
                        </button>
                    </div>
                </form>
            </div>`;
    }
    document.getElementById('batch-modal-'+current_batch).style.display = "block";
    pause();
}

//Send an action to the server
function action_batch(batch_name,action,signal=0){
    $.ajax({
        url: '/ui/batch/action',
        data: {action : action, name:batch_name, signal:signal}
    });
    console.log('Sending action',{action : action, name:batch_name, signal:signal});
}
    
//$(document).ready( get_batch() );
$(document).ready( loop_if_online(get_batch,5000) );