"use strict";
const el = id => document.getElementById(id);
const state = {user:null, lists:[], active:null, entries:[], recipes:[], catalogue:[],
  selectedEntry:null, selectedRecipe:null, listEditing:null, showCompleted:false};
let toastTimer;
function toast(msg) {el("toast").textContent=msg;el("toast").hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>el("toast").hidden=true,4000);}
function csrf() {const v=document.cookie.split("; ").find(x=>x.startsWith("anulist_csrf="));return v?decodeURIComponent(v.slice(13)):"";}
async function api(path, options={}) {
  const method=options.method||"GET",headers={...options.headers};
  if(method!=="GET" && method!=="HEAD") headers["X-CSRF-Token"]=csrf();
  if(options.body!==undefined && !(options.body instanceof FormData)){
    headers["Content-Type"]="application/json";options.body=JSON.stringify(options.body);
  }
  let response;
  try{response=await fetch("/api"+path,{...options,method,headers,credentials:"same-origin"});}
  catch{throw Error("Server unavailable. Your change was not saved.");}
  const data=await response.json().catch(()=>({}));
  if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"Please check your details ("+response.status+").");
  return data;
}
function dialog(name){el(name).showModal();}
function showLogin(){state.user=null;el("authScreen").hidden=false;el("appShell").hidden=true;}
function showApp(){el("authScreen").hidden=true;el("appShell").hidden=false;}
function option(value,name){return new Option(name,value);}
function currentList(){return state.lists.find(l=>l.id===state.active);}
function categorySection(name){
  const heading=document.createElement("h2");heading.className="category-heading";heading.textContent=name;
  return heading;
}
function entryRow(item){
  const wrap=document.createElement("div");wrap.className="entry";
  const button=document.createElement("button");button.type="button";button.className="entry-main";
  button.setAttribute("aria-pressed",String(Boolean(item.checked)));
  button.setAttribute("aria-label",(item.checked?"Mark not bought: ":"Mark bought: ")+item.name);
  const circle=document.createElement("span");circle.className="entry-check";circle.textContent=item.checked?"✓":"";
  circle.setAttribute("aria-hidden","true");button.append(circle);
  const content=document.createElement("span");content.className="entry-content";
  const name=document.createElement("span");name.className="entry-name";name.textContent=item.name;content.append(name);
  const secondary=[item.quantity,item.note].filter(Boolean).join(" · ");
  if(secondary){const sub=document.createElement("span");sub.className="entry-secondary";sub.textContent=secondary;content.append(sub);}
  button.append(content);button.addEventListener("click",()=>toggle(item.id));wrap.append(button);
  if(item.image_key && item.catalogue_id){const photo=document.createElement("img");photo.className="entry-photo";photo.loading="lazy";
    photo.alt="";photo.src="/api/catalogue/"+encodeURIComponent(item.catalogue_id)+"/photo";wrap.append(photo);}
  const details=document.createElement("button");details.type="button";details.className="entry-info";details.textContent="⋯";
  details.setAttribute("aria-label","Edit "+item.name);details.addEventListener("click",()=>editEntry(item.id));wrap.append(details);
  return wrap;
}
function fillEntries(target,items){
  const root=el(target);root.replaceChildren();const groups=new Map();
  for(const item of items){const key=item.category||"Other";if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item);}
  for(const [name,group] of groups){root.append(categorySection(name));for(const item of group)root.append(entryRow(item));}
}
function renderEntries(){
  const remaining=state.entries.filter(i=>!i.checked),done=state.entries.filter(i=>i.checked);
  el("remainingCount").textContent=remaining.length+" left";
  el("doneCount").textContent=done.length;
  el("doneWrap").hidden=!done.length;el("doneItems").hidden=!state.showCompleted;
  el("toggleDone").setAttribute("aria-expanded",String(state.showCompleted));
  el("emptyItems").hidden=state.entries.length!==0;
  fillEntries("items",remaining);fillEntries("doneItems",done);
}
function renderPicker(){
  const select=el("listSelect");select.replaceChildren(...state.lists.map(l=>option(l.id,l.name)));
  if(state.active)select.value=state.active;
  el("currentListName").textContent=currentList()?.name||"Your lists";
  el("addForm").hidden=!state.active;
  el("openBulk").disabled=!state.active;el("manageList").disabled=!state.active;
}
async function loadLists(){
  const list=await api("/lists");
  state.lists=list;
  if(!list.some(l=>l.id===state.active))state.active=list[0]?.id||null;
  renderPicker();
  if(state.active)await loadEntries();
  else{state.entries=[];renderEntries();}
}
async function loadEntries(){
  const id=state.active;if(!id)return;
  const items=await api("/lists/"+encodeURIComponent(id)+"/entries");
  if(id===state.active){state.entries=items;renderEntries();}
}
async function loadCatalogue(q=""){
  state.catalogue=await api("/catalogue?q="+encodeURIComponent(q));
  el("suggestions").replaceChildren(...state.catalogue.map(i=>{
    const node=document.createElement("option");node.value=i.name;node.label=[i.quantity,i.note].filter(Boolean).join(" · ");return node;
  }));
}
async function toggle(id){
  const item=state.entries.find(i=>i.id===id);if(!item)return;
  const original=item.checked;item.checked=!original;renderEntries();
  try{const saved=await api("/entries/"+encodeURIComponent(id),{method:"PATCH",body:{checked:!original,version:item.version}});
    state.entries=state.entries.map(e=>e.id===id?{...e,...saved}:e);renderEntries();}
  catch(error){item.checked=original;renderEntries();toast(error.message);loadEntries().catch(()=>{});}
}
function editEntry(id){
  const item=state.entries.find(i=>i.id===id);if(!item)return;state.selectedEntry=item;
  el("itemName").value=item.name;el("itemQuantity").value=item.quantity;el("itemNote").value=item.note;
  el("itemCategory").value=item.category;el("itemSaveDefault").checked=false;
  el("entryError").textContent="";el("itemPhoto").value="";
  el("itemPhotoBlock").hidden=!item.catalogue_id;
  const preview=el("itemPhotoPreview");preview.hidden=!item.image_key;
  if(item.image_key)preview.src="/api/catalogue/"+encodeURIComponent(item.catalogue_id)+"/photo";
  dialog("entryDialog");
}
async function saveEntry(){
  const item=state.selectedEntry;if(!item)return;
  const data={name:el("itemName").value.trim(),quantity:el("itemQuantity").value.trim(),
    note:el("itemNote").value.trim(),category:el("itemCategory").value.trim(),version:item.version};
  el("entryError").textContent="";
  try{
    await api("/entries/"+encodeURIComponent(item.id),{method:"PATCH",body:data});
    if(el("itemSaveDefault").checked && item.catalogue_id){
      await api("/catalogue/"+encodeURIComponent(item.catalogue_id),{method:"PUT",body:{
        name:data.name,quantity:data.quantity,note:data.note,category:data.category}});
    }
    const photo=el("itemPhoto").files[0];
    if(photo && item.catalogue_id){const form=new FormData();form.append("file",photo);
      await api("/catalogue/"+encodeURIComponent(item.catalogue_id)+"/photo",{method:"POST",body:form});}
    el("entryDialog").close();await loadEntries();toast("Item saved");
  }catch(error){el("entryError").textContent=error.message;}
}
function renderRecipes(){
  const root=el("recipeCards");root.replaceChildren();
  if(!state.recipes.length){root.textContent="No recipes yet. Tap + Recipe to add your first.";return;}
  for(const recipe of state.recipes){
    const button=document.createElement("button");button.type="button";button.className="recipe-card";
    const hint=document.createElement("span");hint.textContent="▤  RECIPE";
    const title=document.createElement("h2");title.textContent=recipe.title;
    const serves=document.createElement("span");serves.textContent="Serves "+recipe.servings;
    button.append(hint,title,serves);button.addEventListener("click",()=>viewRecipe(recipe.id));root.append(button);
  }
}
async function loadRecipes(){state.recipes=await api("/recipes");renderRecipes();}
function parseIngredient(line){
  const raw=line.trim();if(!raw)return null;
  const match=raw.match(/^(\d+(?:\.\d+)?\s*(?:kg|g|ml|l|packs?|x|cups?|tbsp|tsp|pieces?|cloves?)?)\s+(.+)$/i);
  return match?{quantity:match[1].trim(),name:match[2].trim()}:{name:raw,quantity:""};
}
function recipeEditor(recipe=null){
  state.selectedRecipe=recipe;el("recipeDialogTitle").textContent=recipe?"Edit recipe":"New recipe";
  el("recipeName").value=recipe?.title||"";el("recipeServes").value=recipe?.servings||4;
  el("recipeUrl").value=recipe?.source_url||"";el("recipeMethod").value=recipe?.instructions||"";
  el("recipeIngredients").value=(recipe?.ingredients||[]).map(i=>[i.quantity,i.name].filter(Boolean).join(" ")).join("\n");
  el("deleteRecipe").hidden=!recipe;el("recipeError").textContent="";dialog("recipeDialog");
}
async function viewRecipe(id){
  try{
    const recipe=await api("/recipes/"+encodeURIComponent(id));state.selectedRecipe=recipe;
    el("recipeViewTitle").textContent=recipe.title;el("recipeViewMeta").textContent="Serves "+recipe.servings;
    el("recipeViewMethod").textContent=recipe.instructions||"No method added yet.";
    const root=el("recipeViewIngredients");root.replaceChildren();
    for(const ingredient of recipe.ingredients){
      const label=document.createElement("label");label.className="ingredient-choice";
      const input=document.createElement("input");input.type="checkbox";input.value=ingredient.id;input.checked=true;
      const span=document.createElement("span");span.textContent=[ingredient.quantity,ingredient.name].filter(Boolean).join(" ");
      label.append(input,span);root.append(label);
    }
    const select=el("recipeTarget");select.replaceChildren(...state.lists.map(l=>option(l.id,l.name)));
    if(state.active)select.value=state.active;
    el("recipeViewError").textContent="";dialog("recipeViewDialog");
  }catch(error){toast(error.message);}
}
async function saveRecipe(){
  const data={title:el("recipeName").value.trim(),servings:Number(el("recipeServes").value),
    instructions:el("recipeMethod").value,source_url:el("recipeUrl").value.trim(),
    ingredients:el("recipeIngredients").value.split("\n").map(parseIngredient).filter(Boolean)};
  try{
    const id=state.selectedRecipe?.id;
    await api(id?"/recipes/"+encodeURIComponent(id):"/recipes",
      {method:id?"PUT":"POST",body:data});
    el("recipeDialog").close();await loadRecipes();toast("Recipe saved");
  }catch(error){el("recipeError").textContent=error.message;}
}
function listEditor(existing){
  state.listEditing=existing?currentList():null;
  el("listDialogTitle").textContent=existing?"List options":"New list";
  el("listName").value=state.listEditing?.name||"";el("listKind").value=state.listEditing?.kind||"shopping";
  el("listKind").disabled=Boolean(existing);el("deleteList").hidden=!existing;
  el("listFormError").textContent="";dialog("listDialog");
}
async function saveList(){
  const id=state.listEditing?.id;
  try{
    const result=await api(id?"/lists/"+encodeURIComponent(id):"/lists",
      {method:id?"PATCH":"POST",body:{name:el("listName").value.trim(),kind:el("listKind").value}});
    state.active=result.id;el("listDialog").close();await loadLists();toast("List saved");
  }catch(error){el("listFormError").textContent=error.message;}
}
function navigate(page){
  for(const name of ["lists","recipes","settings"])el(name+"Page").hidden=name!==page;
  document.querySelectorAll("[data-page]").forEach(button=>button.classList.toggle("active",button.dataset.page===page));
  if(page==="settings")loadMembers();
}
async function loadMembers(){
  try{
    const root=el("memberList");root.replaceChildren();
    for(const member of await api("/household/members")){
      const row=document.createElement("div");row.className="person";
      const name=document.createElement("strong");name.textContent=member.name;
      const role=document.createElement("span");role.textContent=member.role;
      row.append(name,role);root.append(row);
    }
  }catch(error){toast(error.message);}
}
async function refreshUser(){
  state.user=await api("/auth/me");el("householdName").textContent=state.user.household;
  el("userName").textContent=state.user.name;showApp();await loadLists();await loadRecipes();
}
function bind(){
  el("authMode").addEventListener("click",()=>{
    state.register=!state.register;
    el("authTitle").textContent=state.register?"Join your household":"Welcome back";
    el("authSubmit").textContent=state.register?"Create account":"Sign in";
    el("authMode").textContent=state.register?"Back to sign in":"I have a household invitation";
    el("nameField").hidden=!state.register;el("inviteField").hidden=!state.register;
    el("authPassword").autocomplete=state.register?"new-password":"current-password";
    el("authError").textContent="";
  });
  el("authForm").addEventListener("submit",async event=>{
    event.preventDefault();
    const data={email:el("authEmail").value.trim(),password:el("authPassword").value};
    if(state.register){data.name=el("authName").value.trim();data.invitation=el("authInvite").value.trim();}
    try{await api(state.register?"/auth/register":"/auth/login",{method:"POST",body:data});await refreshUser();}
    catch(error){el("authError").textContent=error.message;}
  });
  const signOut=async()=>{
    try{await api("/auth/logout",{method:"POST"});}catch(error){toast(error.message);}
    showLogin();
  };
  el("logout").addEventListener("click",signOut);
  el("mobileLogout").addEventListener("click",signOut);
  document.querySelectorAll("[data-page]").forEach(button=>button.addEventListener("click",()=>navigate(button.dataset.page)));
  el("listSelect").addEventListener("change",async event=>{
    state.active=event.target.value;renderPicker();
    try{await loadEntries();}catch(error){toast(error.message);}
  });
  let searchTimer;
  el("addInput").addEventListener("input",()=>{
    clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadCatalogue(el("addInput").value).catch(()=>{}),250);
  });
  el("addInput").addEventListener("focus",()=>loadCatalogue(el("addInput").value).catch(()=>{}));
  el("addForm").addEventListener("submit",async event=>{
    event.preventDefault();if(!state.active)return;
    const field=el("addInput"),name=field.value.trim();if(!name)return;
    field.disabled=true;
    try{
      await api("/lists/"+encodeURIComponent(state.active)+"/entries",{method:"POST",body:parseIngredient(name)});
      field.value="";el("listError").textContent="";await loadEntries();
      loadCatalogue().catch(()=>{});field.focus();
    }catch(error){el("listError").textContent=error.message;toast(error.message);}
    finally{field.disabled=false;}
  });
  el("toggleDone").addEventListener("click",()=>{state.showCompleted=!state.showCompleted;renderEntries();});
  el("entryForm").addEventListener("submit",event=>{event.preventDefault();saveEntry();});
  el("deleteEntry").addEventListener("click",async()=>{
    const item=state.selectedEntry;if(!item||!confirm("Delete "+item.name+" from this list?"))return;
    try{await api("/entries/"+encodeURIComponent(item.id),{method:"DELETE"});el("entryDialog").close();await loadEntries();}
    catch(error){el("entryError").textContent=error.message;}
  });
  el("openBulk").addEventListener("click",()=>{el("bulkText").value="";el("bulkError").textContent="";dialog("bulkDialog");});
  el("bulkForm").addEventListener("submit",async event=>{
    event.preventDefault();
    try{const added=await api("/lists/"+encodeURIComponent(state.active)+"/bulk",
      {method:"POST",body:{text:el("bulkText").value}});
      el("bulkDialog").close();await loadEntries();toast("Added "+added.length+" items");
    }catch(error){el("bulkError").textContent=error.message;}
  });
  el("newRecipe").addEventListener("click",()=>recipeEditor());
  el("recipeForm").addEventListener("submit",event=>{event.preventDefault();saveRecipe();});
  el("editRecipe").addEventListener("click",()=>{
    const recipe=state.selectedRecipe;el("recipeViewDialog").close();recipeEditor(recipe);
  });
  el("deleteRecipe").addEventListener("click",async()=>{
    const recipe=state.selectedRecipe;if(!recipe||!confirm("Delete "+recipe.title+"?"))return;
    try{await api("/recipes/"+encodeURIComponent(recipe.id),{method:"DELETE"});
      el("recipeDialog").close();await loadRecipes();}
    catch(error){el("recipeError").textContent=error.message;}
  });
  el("addRecipeIngredients").addEventListener("click",async()=>{
    const recipe=state.selectedRecipe;
    const selected=Array.from(el("recipeViewIngredients").querySelectorAll("input:checked")).map(input=>input.value);
    try{
      const added=await api("/recipes/"+encodeURIComponent(recipe.id)+"/add",
        {method:"POST",body:{list_id:el("recipeTarget").value,ingredient_ids:selected}});
      el("recipeViewDialog").close();toast("Added "+added.length+" ingredients");
      if(state.active===el("recipeTarget").value)await loadEntries();
    }catch(error){el("recipeViewError").textContent=error.message;}
  });
  el("manageList").addEventListener("click",()=>listEditor(true));
  el("createList").addEventListener("click",()=>listEditor(false));
  el("listForm").addEventListener("submit",event=>{event.preventDefault();saveList();});
  el("deleteList").addEventListener("click",async()=>{
    const list=state.listEditing;if(!list||!confirm("Delete "+list.name+" and all of its items?"))return;
    try{await api("/lists/"+encodeURIComponent(list.id),{method:"DELETE"});
      el("listDialog").close();state.active=null;await loadLists();toast("List deleted");}
    catch(error){el("listFormError").textContent=error.message;}
  });
  el("generateInvite").addEventListener("click",async()=>{
    try{const response=await api("/household/invite",{method:"POST"});
      el("inviteCode").textContent=response.code;el("inviteResult").hidden=false;el("inviteMessage").textContent="";}
    catch(error){el("inviteMessage").textContent=error.message;}
  });
  el("copyInvite").addEventListener("click",async()=>{
    try{await navigator.clipboard.writeText(el("inviteCode").textContent);toast("Invitation copied");}
    catch{toast("Select the code and copy it manually");}
  });
  document.querySelectorAll("[data-close]").forEach(button=>button.addEventListener("click",()=>el(button.dataset.close).close()));
  document.querySelectorAll("dialog").forEach(d=>d.addEventListener("click",event=>{if(event.target===d)d.close();}));
}
async function start(){
  bind();
  const connectivity=()=>{el("connection").hidden=navigator.onLine;
    el("connection").textContent="Offline — existing items remain visible, but changes need internet."};
  connectivity();window.addEventListener("online",()=>{connectivity();if(state.user)loadLists().catch(()=>{});});
  window.addEventListener("offline",connectivity);
  if("serviceWorker" in navigator)navigator.serviceWorker.register("/sw.js").catch(()=>{});
  try{await refreshUser();}catch{showLogin();}
  setInterval(async()=>{
    if(!state.user||document.hidden||!navigator.onLine||document.querySelector("dialog[open]"))return;
    try{await loadLists();}catch{}
  },6000);
}
start();
