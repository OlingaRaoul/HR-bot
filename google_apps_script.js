function doGet(e) {
  var action = e.parameter.action;
  var sheetName = e.parameter.sheet;
  
  if (action === "read") {
    return readSheetData(sheetName);
  } else if (action === "get_structure") {
    return getSpreadsheetStructure();
  }
  
  return ContentService.createTextOutput(JSON.stringify({status: "error", message: "Invalid GET action"}))
    .setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  try {
    var postData = JSON.parse(e.postData.contents);
    var action = postData.action;
    var sheetName = postData.sheet;
    
    if (action === "append") {
      return appendCandidate(sheetName, postData.data);
    } else if (action === "update_status") {
      return updateCandidateStatus(sheetName, postData.email, postData.status);
    }
    
    return ContentService.createTextOutput(JSON.stringify({status: "error", message: "Invalid POST action"}))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (error) {
    return ContentService.createTextOutput(JSON.stringify({status: "error", message: error.toString()}))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function getSpreadsheetStructure() {
  try {
    var doc = SpreadsheetApp.getActiveSpreadsheet();
    var sheets = doc.getSheets();
    var structure = {};
    
    for (var i = 0; i < sheets.length; i++) {
      var sheet = sheets[i];
      var name = sheet.getName();
      // Read first row to get headers
      var values = sheet.getRange(1, 1, 1, Math.max(1, sheet.getLastColumn())).getValues();
      var headers = [];
      if (values && values.length > 0) {
        headers = values[0].filter(function(h) { return h.toString().trim() !== ""; });
      }
      structure[name] = headers;
    }
    
    return ContentService.createTextOutput(JSON.stringify({status: "success", structure: structure}))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (error) {
    return ContentService.createTextOutput(JSON.stringify({status: "error", message: error.toString()}))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function readSheetData(sheetName) {
  var doc = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = doc.getSheetByName(sheetName);
  if (!sheet) {
    // Create sheet if it does not exist
    sheet = doc.insertSheet(sheetName);
    var headers = ["Candidate_ID", "Name", "Email", "Role", "Status", "Notes"];
    sheet.appendRow(headers);
    return ContentService.createTextOutput(JSON.stringify({status: "success", data: []}))
      .setMimeType(ContentService.MimeType.JSON);
  }
  
  var values = sheet.getDataRange().getValues();
  if (values.length <= 1) {
    return ContentService.createTextOutput(JSON.stringify({status: "success", data: []}))
      .setMimeType(ContentService.MimeType.JSON);
  }
  
  var headers = values[0];
  var data = [];
  for (var i = 1; i < values.length; i++) {
    var row = values[i];
    var rowData = {};
    for (var j = 0; j < headers.length; j++) {
      rowData[headers[j]] = row[j] !== undefined ? row[j] : "";
    }
    data.push(rowData);
  }
  
  return ContentService.createTextOutput(JSON.stringify({status: "success", data: data}))
    .setMimeType(ContentService.MimeType.JSON);
}

function appendCandidate(sheetName, candidateData) {
  var doc = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = doc.getSheetByName(sheetName);
  if (!sheet) {
    sheet = doc.insertSheet(sheetName);
    var headers = ["Candidate_ID", "Name", "Email", "Role", "Status", "Notes"];
    sheet.appendRow(headers);
  }
  
  var values = sheet.getDataRange().getValues();
  var headers = values[0];
  
  // Check for duplicate Email
  var emailColIdx = headers.indexOf("Email");
  if (emailColIdx !== -1) {
    for (var i = 1; i < values.length; i++) {
      if (values[i][emailColIdx] === candidateData.Email) {
        return ContentService.createTextOutput(JSON.stringify({status: "success", message: "Duplicate email ignored"}))
          .setMimeType(ContentService.MimeType.JSON);
      }
    }
  }
  
  // Align data to headers
  var row = [];
  for (var j = 0; j < headers.length; j++) {
    var key = headers[j];
    row.push(candidateData[key] !== undefined ? candidateData[key] : "");
  }
  
  sheet.appendRow(row);
  return ContentService.createTextOutput(JSON.stringify({status: "success"}))
    .setMimeType(ContentService.MimeType.JSON);
}

function updateCandidateStatus(sheetName, email, newStatus) {
  var doc = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = doc.getSheetByName(sheetName);
  if (!sheet) {
    return ContentService.createTextOutput(JSON.stringify({status: "error", message: "Sheet not found"}))
      .setMimeType(ContentService.MimeType.JSON);
  }
  
  var values = sheet.getDataRange().getValues();
  var headers = values[0];
  
  var emailColIdx = headers.indexOf("Email");
  var statusColIdx = headers.indexOf("Status");
  
  if (emailColIdx === -1 || statusColIdx === -1) {
    return ContentService.createTextOutput(JSON.stringify({status: "error", message: "Required columns missing"}))
      .setMimeType(ContentService.MimeType.JSON);
  }
  
  for (var i = 1; i < values.length; i++) {
    if (values[i][emailColIdx] === email) {
      sheet.getRange(i + 1, statusColIdx + 1).setValue(newStatus);
      return ContentService.createTextOutput(JSON.stringify({status: "success"}))
        .setMimeType(ContentService.MimeType.JSON);
    }
  }
  
  return ContentService.createTextOutput(JSON.stringify({status: "error", message: "Candidate not found"}))
    .setMimeType(ContentService.MimeType.JSON);
}

function onEdit(e) {
  var sheet = e.source.getActiveSheet();
  var range = e.range;
  var row = range.getRow();
  
  if (row <= 1) return;
  
  var headers = sheet.getRange(1, 1, 1, Math.max(1, sheet.getLastColumn())).getValues()[0];
  
  // 1. Automatically update "Last Modified" timestamp
  var lastModifiedIdx = headers.indexOf("Last Modified");
  if (lastModifiedIdx === -1) {
    lastModifiedIdx = headers.indexOf("Last_Modified");
  }
  
  if (lastModifiedIdx !== -1) {
    var lastModifiedCol = lastModifiedIdx + 1;
    if (range.getColumn() !== lastModifiedCol) {
      sheet.getRange(row, lastModifiedCol).setValue(new Date());
    }
  }
  
  // 2. Automatically generate "Candidate_ID"
  var candidateIdIdx = headers.indexOf("Candidate_ID");
  if (candidateIdIdx === -1) {
    candidateIdIdx = headers.indexOf("Candidate ID");
  }
  var emailIdx = headers.indexOf("Email");
  if (emailIdx === -1) {
    emailIdx = headers.indexOf("Contact Email");
  }
  if (emailIdx === -1) {
    emailIdx = headers.indexOf("Contact Email               ");
  }
  
  if (candidateIdIdx !== -1) {
    var candidateIdCol = candidateIdIdx + 1;
    
    // Lock Candidate_ID from manual edits by reverting changes (handles edits, deletions, and new values)
    if (range.getColumn() === candidateIdCol) {
      var sheetName = sheet.getName();
      if (sheetName === "Entries" || sheetName === "Demo Task Status" || sheetName === "Next Steps") {
        var oldVal = e.oldValue;
        if (oldVal !== undefined && oldVal !== null && oldVal.toString().trim() !== "") {
          range.setValue(oldVal);
        } else {
          range.clearContent();
        }
        e.source.toast("⚠️ Candidate ID is locked and cannot be edited manually!", "Permission Denied");
        return;
      }
    }
    
    if (emailIdx !== -1) {
      var emailCol = emailIdx + 1;
      var currentIdVal = sheet.getRange(row, candidateIdCol).getValue();
      var emailVal = sheet.getRange(row, emailCol).getValue();
      
      if (currentIdVal.toString().trim() === "" && emailVal.toString().trim() !== "") {
        var newId = "SG-" + (10000 + row);
        sheet.getRange(row, candidateIdCol).setValue(newId);
      }
    }
  }
}

function initializeSheetColumns() {
  var doc = SpreadsheetApp.getActiveSpreadsheet();
  
  // 1. First, make sure the Candidate_ID and Last_Modified columns are added to all three sheets
  var sheetsToProcess = ["Entries", "Demo Task Status", "Next Steps"];
  for (var i = 0; i < sheetsToProcess.length; i++) {
    var sheet = doc.getSheetByName(sheetsToProcess[i]);
    if (sheet) {
      var lastCol = sheet.getLastColumn();
      var headers = lastCol > 0 ? sheet.getRange(1, 1, 1, lastCol).getValues()[0] : [];
      
      // Add Candidate_ID to Column A if it doesn't exist
      var cidIdx = headers.indexOf("Candidate_ID");
      if (cidIdx === -1) cidIdx = headers.indexOf("Candidate ID");
      if (cidIdx === -1) {
        sheet.insertColumnBefore(1);
        lastCol = sheet.getLastColumn();
        headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
      }
      
      // Clear validation rules for the entire Candidate_ID column to prevent errors
      var cleanCidIdx = headers.indexOf("Candidate_ID");
      if (cleanCidIdx === -1) cleanCidIdx = headers.indexOf("Candidate ID");
      if (cleanCidIdx !== -1) {
        var maxRows = Math.max(1, sheet.getLastRow());
        sheet.getRange(1, cleanCidIdx + 1, maxRows, 1).clearDataValidations();
        sheet.getRange(1, cleanCidIdx + 1).setValue("Candidate_ID");
      }
      
      // Add Last_Modified to the end if it doesn't exist
      var lmIdx = headers.indexOf("Last_Modified");
      if (lmIdx === -1) lmIdx = headers.indexOf("Last Modified");
      if (lmIdx === -1) {
        sheet.getRange(1, lastCol + 1).setValue("Last_Modified");
      }
    }
  }
  
  // 2. Load the Entries sheet data to build a map of Name -> Candidate_ID
  var entriesSheet = doc.getSheetByName("Entries");
  var nameToIdMap = {};
  if (entriesSheet) {
    var lastCol = entriesSheet.getLastColumn();
    var lastRow = entriesSheet.getLastRow();
    if (lastRow > 1) {
      var headers = entriesSheet.getRange(1, 1, 1, lastCol).getValues()[0];
      
      var cidColIdx = headers.indexOf("Candidate_ID");
      if (cidColIdx === -1) cidColIdx = headers.indexOf("Candidate ID");
      
      var firstNameColIdx = headers.indexOf("First Name");
      var lastNameColIdx = headers.indexOf("Last Name");
      
      var emailColIdx = headers.indexOf("Email");
      if (emailColIdx === -1) emailColIdx = headers.indexOf("Contact Email");
      if (emailColIdx === -1) emailColIdx = headers.indexOf("Contact Email               ");
      
      if (cidColIdx !== -1) {
        var cidCol = cidColIdx + 1;
        var fNameCol = firstNameColIdx + 1;
        var lNameCol = lastNameColIdx + 1;
        var emailCol = emailColIdx + 1;
        
        var idValues = entriesSheet.getRange(2, cidCol, lastRow - 1, 1).getValues();
        var fNameValues = firstNameColIdx !== -1 ? entriesSheet.getRange(2, fNameCol, lastRow - 1, 1).getValues() : [];
        var lNameValues = lastNameColIdx !== -1 ? entriesSheet.getRange(2, lNameCol, lastRow - 1, 1).getValues() : [];
        var emailValues = emailColIdx !== -1 ? entriesSheet.getRange(2, emailCol, lastRow - 1, 1).getValues() : [];
        
        // Loop through Entries, generate missing IDs, and build nameToIdMap
        for (var r = 0; r < idValues.length; r++) {
          var rowNum = r + 2;
          var currentId = idValues[r][0].toString().trim();
          var emailVal = emailColIdx !== -1 ? emailValues[r][0].toString().trim() : "";
          
          var fNameVal = firstNameColIdx !== -1 ? fNameValues[r][0].toString().trim() : "";
          var lNameVal = lastNameColIdx !== -1 ? lNameValues[r][0].toString().trim() : "";
          var fullName = (fNameVal + " " + lNameVal).trim();
          
          if (currentId === "" && emailVal !== "") {
            currentId = "SG-" + (10000 + rowNum);
            entriesSheet.getRange(rowNum, cidCol).setValue(currentId);
          }
          
          if (currentId !== "" && fullName !== "") {
            nameToIdMap[fullName.toLowerCase()] = currentId;
          }
        }
      }
    }
  }
  
  // 3. Populate Candidate_IDs in "Demo Task Status" and "Next Steps" using nameToIdMap
  var otherSheets = ["Demo Task Status", "Next Steps"];
  for (var s = 0; s < otherSheets.length; s++) {
    var sheet = doc.getSheetByName(otherSheets[s]);
    if (sheet) {
      var lastCol = sheet.getLastColumn();
      var lastRow = sheet.getLastRow();
      if (lastRow > 1) {
        var headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
        var cidColIdx = headers.indexOf("Candidate_ID");
        if (cidColIdx === -1) cidColIdx = headers.indexOf("Candidate ID");
        
        if (cidColIdx !== -1) {
          var cidCol = cidColIdx + 1;
          var idValues = sheet.getRange(2, cidCol, lastRow - 1, 1).getValues();
          
          for (var r = 0; r < idValues.length; r++) {
            var rowNum = r + 2;
            var currentId = idValues[r][0].toString().trim();
            
            if (currentId === "") {
              // Extract candidate name from row content
              var candidateName = "";
              if (otherSheets[s] === "Demo Task Status") {
                var evalColIdx = headers.indexOf("Demo Task Evaluation");
                if (evalColIdx === -1) evalColIdx = headers.indexOf("Demo Task Evaluation               ");
                if (evalColIdx !== -1) {
                  var evalVal = sheet.getRange(rowNum, evalColIdx + 1).getValue().toString().trim();
                  candidateName = evalVal.replace("Demo Task Evaluation - ", "").replace("Task Evaluation - ", "").trim();
                }
              } else if (otherSheets[s] === "Next Steps") {
                var nameColIdx = headers.indexOf("Name");
                if (nameColIdx !== -1) {
                  candidateName = sheet.getRange(rowNum, nameColIdx + 1).getValue().toString().trim();
                }
              }
              
              if (candidateName !== "" && nameToIdMap[candidateName.toLowerCase()]) {
                var mappedId = nameToIdMap[candidateName.toLowerCase()];
                sheet.getRange(rowNum, cidCol).setValue(mappedId);
              }
            }
          }
        }
      }
    }
  }
}


