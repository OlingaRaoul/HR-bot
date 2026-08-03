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
    
    // Lock Candidate_ID from manual edits by reverting changes
    if (range.getColumn() === candidateIdCol) {
      var oldVal = e.oldValue;
      if (oldVal !== undefined && oldVal !== null && oldVal.toString().trim() !== "") {
        range.setValue(oldVal);
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
  var sheets = doc.getSheets();
  for (var i = 0; i < sheets.length; i++) {
    var sheet = sheets[i];
    var name = sheet.getName();
    if (name === "Entries" || name === "Demo Task Status" || name === "Next Steps") {
      var lastCol = sheet.getLastColumn();
      var headers = lastCol > 0 ? sheet.getRange(1, 1, 1, lastCol).getValues()[0] : [];
      
      // 1. Add Candidate_ID to Column A if it doesn't exist
      var cidIdx = headers.indexOf("Candidate_ID");
      if (cidIdx === -1) cidIdx = headers.indexOf("Candidate ID");
      if (cidIdx === -1) {
        sheet.insertColumnBefore(1);
        sheet.getRange(1, 1).clearDataValidations();
        sheet.getRange(1, 1).setValue("Candidate_ID");
        // Reload headers
        lastCol = sheet.getLastColumn();
        headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
      }
      
      // 2. Add Last_Modified to the end if it doesn't exist
      var lmIdx = headers.indexOf("Last_Modified");
      if (lmIdx === -1) lmIdx = headers.indexOf("Last Modified");
      if (lmIdx === -1) {
        sheet.getRange(1, lastCol + 1).setValue("Last_Modified");
        lastCol = sheet.getLastColumn();
        headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
      }
      
      // 3. Generate Candidate_IDs for all existing candidates
      var lastRow = sheet.getLastRow();
      if (lastRow > 1) {
        var emailColIdx = headers.indexOf("Email");
        if (emailColIdx === -1) emailColIdx = headers.indexOf("Contact Email");
        if (emailColIdx === -1) emailColIdx = headers.indexOf("Contact Email               ");
        
        var cidColIdx = headers.indexOf("Candidate_ID");
        if (cidColIdx === -1) cidColIdx = headers.indexOf("Candidate ID");
        
        if (cidColIdx !== -1 && emailColIdx !== -1) {
          var cidCol = cidColIdx + 1;
          var emailCol = emailColIdx + 1;
          
          var idValues = sheet.getRange(2, cidCol, lastRow - 1, 1).getValues();
          var emailValues = sheet.getRange(2, emailCol, lastRow - 1, 1).getValues();
          
          for (var r = 0; r < idValues.length; r++) {
            var rowNum = r + 2;
            var currentId = idValues[r][0];
            var emailVal = emailValues[r][0];
            if (currentId.toString().trim() === "" && emailVal.toString().trim() !== "") {
              var newId = "SG-" + (10000 + rowNum);
              sheet.getRange(rowNum, cidCol).setValue(newId);
            }
          }
        }
      }
    }
  }
}


