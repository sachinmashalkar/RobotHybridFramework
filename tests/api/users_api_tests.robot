*** Settings ***
Documentation       REST API smoke tests using the custom APIClient.

Resource            ../../resources/common/imports.resource

Suite Setup         Begin Api Suite

Test Tags           api    smoke


*** Test Cases ***
Get Single User Returns 200
    ${response}=    API.Send Request    GET    /users/2    expected_status=200
    API.Response Json Should Contain Key    ${response}    name

List Users Returns Limited Payload
    ${response}=    API.Send Request    GET    /users    params=${{ {"_limit": 3} }}    expected_status=200
    ${body}=    Set Variable    ${response.json()}
    Length Should Be    ${body}    3

Create Post Returns 201
    ${payload}=    Create Dictionary    title=devin    body=automation    userId=1
    ${response}=    API.Send Request    POST    /posts    payload=${payload}    expected_status=201
    API.Response Json Should Contain Key    ${response}    id

User Posts Endpoint Returns Non Empty List
    ${response}=    API.Send Request    GET    /users/1/posts    expected_status=200
    ${body}=    Set Variable    ${response.json()}
    Should Not Be Empty    ${body}
