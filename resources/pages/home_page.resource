*** Settings ***
Documentation       Page object for the-internet.herokuapp.com landing page.

Resource            base_page.resource


*** Variables ***
${HOME_HEADING}     css=h1.heading
${HOME_LINKS}       css=ul li a


*** Keywords ***
Open Home Page
    Navigate To Path    /
    Page Should Be Ready
    Wait Until Element Is Visible    ${HOME_HEADING}

Home Page Heading Should Be
    [Arguments]    ${expected}
    Element Should Contain Text    ${HOME_HEADING}    ${expected}

Get Home Link Count
    ${count}=    Get Element Count    ${HOME_LINKS}
    RETURN    ${count}
