"""Metacontroller webhook handler for a JobTree Kubernetes controller"""

import json
from datetime import datetime
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, List, Optional, Union, Tuple

Dependency = Tuple[str, str]  # (job_name, phase)
Dependencies = List[Dependency]
DependencyMap = List[Tuple[str, Dependencies]]  # [(job_name, [...])]
Phase = Tuple[str, str]  # (job_name, phase)
Phases = List[Phase]


def get_job_phase(job_name: str, phases: Phases) -> Optional[str]:
    phases_dict = {job_name: job_phase
                   for job_name, job_phase in phases}
    return phases_dict.get(job_name)


def set_job_phase(job_name: str, phases: Phases, phase: str) -> None:
    for index, item in enumerate(phases):
        name = item[0]
        if name == job_name:
            phases[index] = (job_name, phase)
            break
    else:
        phases.append((job_name, phase))


def phase_matches(dependency: Dependency,
                  phases: Phases) -> bool:
    """Return True if the dependency is currently in the required phase

    The custom internal phase identifier ``Disappeared`` is assumed to be used
    for jobs whose pods were ``Running`` in a previous invocation but
    disappeared without turning into ``Succeeded`` or ``Failed``. In such
    situations, the job is assumed to have succeeded. It is unclear whether
    this is a bug or an intentional feature of Metacontroller.
    See: https://github.com/GoogleCloudPlatform/metacontroller/issues/97

    """
    dependency_name, dependency_phase = dependency
    current_phase = get_job_phase(dependency_name, phases)
    if dependency_phase == 'Succeeded':
        return current_phase in ['Succeeded', 'Disappeared']
    else:
        return current_phase == dependency_phase


def should_run(job_name: str,
               phases: Phases,
               my_dependencies: Dependencies) -> bool:
    """Determine whether a particular job should run or not

    The custom internal phase identifier ``Disappeared`` is assumed to be used
    for jobs whose pods were ``Running`` in a previous invocation but
    disappeared without turning into ``Succeeded`` or ``Failed``. In such
    situations, the job is assumed to have succeeded. It is unclear whether
    this is a bug or an intentional feature of Metacontroller.
    See: https://github.com/GoogleCloudPlatform/metacontroller/issues/97

    :param job_name: The name of the job
    :param phases: Recorded last phases of each job
    :param my_dependencies: Dependencies of the job
    :return: ``True`` if the job should be run or kept running

    """
    phase = get_job_phase(job_name, phases)
    if phase in ['Succeeded', 'Disappeared']:
        return False
    dependencies_succeeded = all(phase_matches(dependency, phases)
                                 for dependency in my_dependencies)
    return dependencies_succeeded


def calculate_jobs(all_dependencies: DependencyMap,
                   phases: Phases) -> List[str]:
    """Determine which jobs should be run or kept runnnig

    :param all_dependencies: All dependencies between jobs
    :param phases: Recorded last phases of each job
    :return: Names of jobs which should be run or kept running

    """
    return [str(job_name) for job_name, job_dependencies in all_dependencies
            if should_run(str(job_name), phases, job_dependencies)]


KubeData = Union[Any, Dict[str, Any]]


def noquotes(obj: Union[List, Dict]) -> str:
    """Shorter YAML-like repr for lists and dicts, used for logging

    :param obj: The list or dict to dump as a string
    :return: The string representation of the list or dict

    """
    return repr(obj).replace("'", "")


def getpath(root: KubeData,
            path: str,
            default: Any = Ellipsis) -> KubeData:
    """Extract a value from nested dictionaries, with optional default value

    :param root: The nested dictionaries to extract a value from
    :param path: A colon-separated string path of dictionary keys to walk
    :param default: Default value to return if any key in the path is missing
    :return: Value at given path, or default value if keys missing along path

    """
    next_item, *rest = path.split(':')
    if rest:
        # Not the last path element yet. Next value must be a dict. If missing,
        # return default value or raise a `KeyError`.
        if default is Ellipsis:
            value = root[next_item]
        else:
            value = root.get(next_item, {})
        return getpath(value, ':'.join(rest), default)
    else:
        # The value for the end of the path can be of any type. If missing,
        # return default value or raise a `KeyError`.
        if default is Ellipsis:
            return root[next_item]
        else:
            return root.get(next_item, default)


def handle_json_request(
    request_data: Dict,
    calculator_func: Callable[[DependencyMap, Phases], List[str]]) -> Dict:
    """Return state and desired pods based on current Kubernetes status

    Collect relevant information from the Kubernetes controller sync webhook
    call. Pass the information to the framework independent sync function, and
    turn the result into a data structure expected by the Kubernetes
    controller.

    Keep last phase information from pods which have already succeeded or
    failed but are no longer around. Use that information to determine when
    dependent jobs can be started.

    Work around Metacontroller's strange double invocation by recording the
    second invocation where a running pod disappears with the internal
    ``Disappeared`` phase.

    :param request_data: The deserialized JSON data struture from the
                         metacontroller sync HTTP POST body
    :param calculator_func: The function which calculates desired jobs to run
                            or keep running based on current and past pod
                            phases
    :return: The status to pass to subsequent calls and the specifications for
             the pods which should be run or kept running

    """
    get = partial(getpath, request_data)

    counter = get('parent:status:counter', 0)  # type: int
    print('- counter: {}'.format(counter))
    print('  time: {}'.format(datetime.utcnow().isoformat('T', 'seconds')))

    # Child pod naming
    name_prefix = '{}-'.format(get('parent:metadata:name'))

    def is_my_child(child_pod_name: str) -> bool:
        return child_pod_name.startswith(name_prefix)

    def extract_name(child_pod_name: str) -> str:
        return child_pod_name[len(name_prefix):]

    # Helper for creating child pod definitions
    restart_policy = get('parent:spec:template:spec:restartPolicy', 'Never')

    def new_pod(container: KubeData) -> KubeData:
        return {'apiVersion': 'v1',
                'kind': 'Pod',
                'metadata': {'name': '{}{}'.format(name_prefix,
                                                   container['name'])},
                'spec': {'containers': [container],
                         'restartPolicy': restart_policy}}

    # Merge previous child pod phases with current phases
    previous_phases = [(job_name, phase)
                       for job_name, phase in get('parent:status:phases', [])]
    phases = previous_phases.copy()
    current_jobs = {}
    for pod_name, value in get('children:Pod.v1', {}).items():
        if is_my_child(pod_name):
            job_name = extract_name(pod_name)
            current_jobs[job_name] = value['status']['phase']
            if get_job_phase(job_name, phases) != 'Succeeded':
                set_job_phase(job_name, phases, value['status']['phase'])
    for job_name, phase in phases:
        if phase == 'Running' and job_name not in current_jobs:
            print('  WARNING 31: Job {} was Running but disappeared. Assuming '
                  'it to have succeeded.'.format(job_name))
            set_job_phase(job_name, phases, 'Disappeared')

    # Compute desired child pods based on observed and past state
    dependencies = [
        (job_name, [(dep_job_name, dep_phase)
                    for dep_job_name, dep_phase in job_dependencies])
        for job_name, job_dependencies in get('parent:spec:dependencies', [])]
    desired_job_names = calculator_func(dependencies, phases)

    # Generate the desired child object(s)
    desired_pods = [
        new_pod(container)
        for container in list(get('parent:spec:template:spec:containers', []))
        if container['name'] in desired_job_names]

    # Complete the log entry
    print('  phases from previous call:', noquotes(previous_phases))
    print('  current pod phases:', noquotes(current_jobs))
    print('  phases combined:', noquotes(phases))
    print('  desired jobs:', noquotes(desired_job_names), flush=True)

    # Pass the phases of all current and already removed pods to future calls.
    # Return the desired pods.
    return {'status': {'phases': phases,
                       'counter': counter + 1},
            'children': desired_pods}


class JobTreeRequestHandler(BaseHTTPRequestHandler):
    """Handler for metacontroller webhook HTTP requests"""

    json_handler_func = handle_json_request
    dependency_calculator_func = calculate_jobs

    def do_POST(self) -> None:
        """Handle the JSON POST webhook

        Deserializes the request body JSON and passes it on to the main
        controller logic. Serializes results back to an JSON response.

        """
        content_length = int(str(self.headers['content-length']))
        request_body = self.rfile.read(content_length)
        request_data = json.loads(request_body)
        cls = type(self)  # Mypy work-around - `self.` causes errors
        response_json = cls.json_handler_func(request_data,
                                              cls.dependency_calculator_func)
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        response_content = json.dumps(response_json,
                                      sort_keys=True).encode('utf-8')
        self.wfile.write(response_content)


def main() -> None:
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument('-i', '--ip', default='')
    parser.add_argument('-p', '--port', type=int, default=80)
    opts = parser.parse_args()
    HTTPServer((opts.ip, opts.port), JobTreeRequestHandler).serve_forever()


if __name__ == '__main__':
    main()
