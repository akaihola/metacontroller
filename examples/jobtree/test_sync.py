import pytest

import sync


@pytest.mark.parametrize(
    'data, path, default, expect',
    [({}, 'outer', Ellipsis, KeyError),
     ({}, 'outer', 'default', 'default'),
     ({}, 'outer:inner', Ellipsis, KeyError),
     ({}, 'outer:inner', 'default', 'default'),
     ({'outer': 'value'}, 'missing', Ellipsis, KeyError),
     ({'outer': 'value'}, 'missing', 'default', 'default'),
     ({'outer': 'value'}, 'outer', Ellipsis, 'value'),
     ({'outer': 'value'}, 'outer', 'default', 'value'),
     ({'outer': 'value'}, 'outer:inner', Ellipsis, TypeError),
     ({'outer': 'value'}, 'outer:inner', 'default', AttributeError),
     ({'outer': {}}, 'outer', Ellipsis, {}),
     ({'outer': {}}, 'outer', 'default', {}),
     ({'outer': {}}, 'outer:inner', Ellipsis, KeyError),
     ({'outer': {}}, 'outer:inner', 'default', 'default'),
     ({'outer': {'inner': 'value'}}, 'outer', Ellipsis, {'inner': 'value'}),
     ({'outer': {'inner': 'value'}}, 'outer', 'default', {'inner': 'value'}),
     ({'outer': {'inner': 'value'}}, 'outer:inner', Ellipsis, 'value'),
     ({'outer': {'inner': 'value'}}, 'outer:inner', 'default', 'value'),
     ({'outer': {'inner': 'value'}}, 'outer:missing', Ellipsis, KeyError),
     ({'outer': {'inner': 'value'}}, 'outer:missing', 'default', 'default')])
def test_getpath(data, path, default, expect):
    try:
        result = sync.getpath(data, path, default)
    except Exception as exc:
        if expect is not type(exc):
            raise
    else:
        assert result == expect


def test_dummy():
    data = {
        'controller': {'status': {}},
        'parent': {
            'metadata': {'name': 'MyName'},
            'spec': {'dependencies': {'EXAMPLE CONTAINER': []},
                     'template': {
                         'spec': {
                             'containers': [{'name': 'EXAMPLE CONTAINER'}]}}}},
        'children': {'Pod.v1': {}}}

    response = sync.handle_json_request(data, sync.calculate_jobs)

    assert response == {
        'children': [{'apiVersion': 'v1',
                      'kind': 'Pod',
                      'metadata': {'name': 'MyName-EXAMPLE CONTAINER'},
                      'spec': {'containers': [{'name': 'EXAMPLE CONTAINER'}],
                               'restartPolicy': 'Never'}}],
        'status': {'counter': 1,
                   'phases': {}}}
