*** Settings ***
Documentation       REST API smoke tests using the custom APIClient.

Resource            ../../resources/common/imports.resource

Suite Setup         Begin Api Suite

Test Tags           api    smoke


*** Test Cases ***
Get Single User Returns 200
    ${response}=    API.Send Request    GET    /users/2    expected_status=200
    API.Response Json Should Contain Key    ${response}    data

List Users Returns Paginated Payload
    ${response}=    API.Send Request    GET    /users    params=${{ {"page": 2} }}    expected_status=200
    ${body}=    Set Variable    ${response.json()}
    Should Be Equal As Integers    ${body}[page]    2
    Length Should Be    ${body}[data]    ${body}[per_page]

Create User Returns 201
    ${payload}=    Create Dictionary    name=devin    job=automation
    ${response}=    API.Send Request    POST    /users    payload=${payload}    expected_status=201
    API.Response Json Should Contain Key    ${response}    id

Unknown User Returns 404
    API.Send Request    GET    /users/23    expected_status=404
