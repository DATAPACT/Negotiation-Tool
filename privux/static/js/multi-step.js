// Design taken from https://bbbootstrap.com/snippets/multi-step-form-wizard-animated-progressbar-53000683#
$(document).ready(function(){

// var current_fs, next_fs, previous_fs; //fieldsets
// var opacity;
// var current = 1;
// var steps = $("fieldset").length;
//
// setProgressBar(current);
//
// function showStep(current_fs, next_fs) {
//      $("#progressbar li").eq($("fieldset").index(next_fs)).addClass("active");
//
//     //show the next fieldset
//     next_fs.show();
//     //hide the current fieldset with style
//     current_fs.animate({opacity: 0}, {
//         step: function(now) {
//             // for making fielset appear animation
//             opacity = 1 - now;
//
//             current_fs.css({
//                 'display': 'none',
//                 'position': 'relative'
//             });
//             next_fs.css({'opacity': opacity});
//         },
//         duration: 500
//     });
//     setProgressBar(++current);
// }
//
// $(".next").click(function(){
//
//     current_fs = $(this).parent();
//     next_fs = $(this).parent().next();
//
//     var currentID = $(this).attr('id');
//     alert(currentID);
//     if (currentID=="step1-next") {
//          var selectedData = $('#selectcontext').val();
//          var selectdata  =   $('#selectList').val().length;
//          if (selectdata == 0 ){
//             alert("Please select the data you want to collect (or process)");
//             return false;
//          }
//
//
//          var selectedValuesByOptgroup = {};
//          var totalOptionsByOptgroup = {};
//          var optgroups = $('#selectList optgroup');
//         //
//         optgroups.each(function() {
//           var optgroupLabel = $(this).attr('label');
//           var optionsCount = $(this).find('option').length;
//
//           // Store total options count per optgroup
//           totalOptionsByOptgroup[optgroupLabel] = optionsCount;
//         });
//
//          $('#selectList option:selected').each(function() {
//           var optgroupLabel = $(this).closest('optgroup').attr('label');
//
//           var optionValue = $(this).val();
//
//           if (!selectedValuesByOptgroup[optgroupLabel]) {
//             selectedValuesByOptgroup[optgroupLabel] = {
//               options: [],
//               count: 0
//             };
//           }
//           selectedValuesByOptgroup[optgroupLabel].options.push(optionValue);
//           selectedValuesByOptgroup[optgroupLabel].count++;
//         });
//
//         var finaldata = [];
//         for (var optgroupLabel in selectedValuesByOptgroup) {
//
//             if (optgroupLabel != "Others"){ // if not others
//                 if (totalOptionsByOptgroup[optgroupLabel] == selectedValuesByOptgroup[optgroupLabel].count){
//                     finaldata.push(optgroupLabel.toLowerCase());
//                 }else {
//                     finaldata.push(selectedValuesByOptgroup[optgroupLabel].options.join(', '));
//                 }
//             }else{
//                 finaldata.push(selectedValuesByOptgroup[optgroupLabel].options.join(', '));
//             }
//         }
//         console.log("**************************");
//         console.log(finaldata);
//         console.log("**************************");
//                  if (selectedData == "selectcontext") {
//                 alert("Please select a context");
//                 return false;
//          }
//     //everything is good. perform the ajax request
//         alert("ajax request");
//             $.ajax({
//                 url: '/predict_pii_data', // the endpoint
//                 data: {
//                     'selectedData': finaldata,
//                     'selectedContext': selectedData
//                 },
//                  type: 'GET',
//                  dataType: 'json',
//                 success: function (data) {
//                     console.log(data);
//                     if (data['status'] == 'success') {
//                         console.log(data['status']);
//                         // showStep(current_fs, next_fs);
//                     }
//                 }
//             });
//
//     }
//
//
//     console.log("******************");
//     alert(current_fs);
//     console.log(current_fs);
//     console.log("******************");
//     //Add Class Active
//     // showStep(current_fs, next_fs);
//
// });
//
// $(".previous").click(function(){
//
//     current_fs = $(this).parent();
//     previous_fs = $(this).parent().prev();
//
//     //Remove class active
//     $("#progressbar li").eq($("fieldset").index(current_fs)).removeClass("active");
//
//     //show the previous fieldset
//     previous_fs.show();
//
//     //hide the current fieldset with style
//     current_fs.animate({opacity: 0}, {
//         step: function(now) {
//             // for making fielset appear animation
//             opacity = 1 - now;
//
//             current_fs.css({
//                 'display': 'none',
//                 'position': 'relative'
//             });
//             previous_fs.css({'opacity': opacity});
//         },
//         duration: 500
//     });
//     setProgressBar(--current);
// });
//
// function setProgressBar(curStep){
//     var percent = parseFloat(100 / steps) * curStep;
//     percent = percent.toFixed();
//     $(".progress-bar")
//       .css("width",percent+"%")
// }
//
// $(".submit").click(function(){
//     return false;
// })

});