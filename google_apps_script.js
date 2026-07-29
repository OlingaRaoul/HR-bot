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
