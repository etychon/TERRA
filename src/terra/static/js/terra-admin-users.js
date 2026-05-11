(function () {
  const showBtn = document.getElementById("terra-show-add-user");
  const panel = document.getElementById("terra-add-user-panel");
  const cancelBtn = document.getElementById("terra-cancel-add-user");
  if (!showBtn || !panel) {
    return;
  }
  showBtn.addEventListener("click", function () {
    panel.hidden = false;
    showBtn.hidden = true;
    const email = document.getElementById("new_email");
    if (email) {
      email.focus();
    }
  });
  if (cancelBtn) {
    cancelBtn.addEventListener("click", function () {
      panel.hidden = true;
      showBtn.hidden = false;
    });
  }
})();
