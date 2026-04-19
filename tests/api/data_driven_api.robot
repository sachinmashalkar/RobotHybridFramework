*** Settings ***
Documentation       Data-driven API suite. Each row in ``testdata/api_users.csv``
...                 becomes an independent test case.

Library             DataDriver    ${CURDIR}/../../testdata/api_users.csv    dialect=excel    encoding=utf_8
Resource            ../../resources/common/imports.resource

Suite Setup         Begin Api Suite
Test Template       Verify User Payload

Test Tags           api    data-driven


*** Test Cases ***
Fetch User Scenario    default    default


*** Keywords ***
Verify User Payload
    [Arguments]    ${user_id}    ${expected_name}
    ${response}=    API.Send Request    GET    /users/${user_id}    expected_status=200
    ${body}=    Set Variable    ${response.json()}
    Should Be Equal    ${body}[name]    ${expected_name}
